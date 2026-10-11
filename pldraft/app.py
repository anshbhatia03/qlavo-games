"""PL Draft — Premier League auction draft game. qlavo.online/pl
2-4 players, £100m budget, hidden position ratings, no visible scores.

Phases: lobby -> setup (formation pick) -> draft (auction loop) -> done
"""
from __future__ import annotations

import asyncio
import json
import random
import secrets
import string
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse

import sys
sys.path.insert(0, str(Path(__file__).parent))
from formations import FORMATION_NAMES, slots_for, back3, auto_assign

BASE = Path(__file__).parent
app = FastAPI(title="PL Draft — Qlavo")

POOL = json.loads((BASE / "data" / "pool.json").read_text())
for _p in POOL:
    _p["id"] = secrets.token_hex(4)

START_BUDGET = 100.0
MIN_OPEN = 1.0
MIN_RAISE = 0.5
SLOT_RESERVE = 1.0  # every empty XI slot must keep £1m available
BID_WINDOW = 30.0    # no bids yet: 30s then unsold
RESET_WINDOW = 15.0  # after first bid: each bid resets the clock to 15s

SQUAD_MIN = 11
SQUAD_MAX = 15


def card(p: dict) -> dict:
    """Public card — everything except ratings."""
    return {
        "id": p["id"], "name": p["name"], "pos": p["pos"], "nat": p["nat"],
        "club": p["club"], "era": p["era"], "ht": p["ht"], "wt": p["wt"],
        "pace": p["pace"], "note": p["note"],
    }


def new_code() -> str:
    return "".join(random.choice(string.ascii_uppercase) for _ in range(4))


def new_id() -> str:
    return secrets.token_urlsafe(8).replace("-", "").replace("_", "")


def draw_queue(room: "Room") -> list[dict]:
    """Every still-available player, in a fresh random order.

    The auction does not walk a position quota. It pops this shuffled list
    and stops as soon as every squad has at least SQUAD_MIN.
    """
    used = {pp["id"] for room_ in ROOMS.values() for pp in room_.sold} | \
           {pp["id"] for room_ in ROOMS.values() for pp in room_.unsold}
    # Sold/unsold ids are shared across rooms so two live games don't auction
    # the same card. A private game; acceptable.
    available = [p for p in POOL if p["id"] not in used]
    random.shuffle(available)
    return [card(p) for p in available]


def everyone_capped(room: "Room") -> bool:
    players = list(room.players.values())
    return bool(players) and all(len(c.squad) >= SQUAD_MAX for c in players)


def ask_price(room: "Room") -> float:
    hi = room.highest_bid()
    if not hi:
        return MIN_OPEN
    return round(hi[1] + MIN_RAISE, 2)


def can_raise(room: "Room", pid: str) -> bool:
    c = room.players.get(pid)
    if not c or len(c.squad) >= SQUAD_MAX:
        return False
    return room.max_bid(pid) + 0.001 >= ask_price(room)


def auto_fold(room: "Room") -> None:
    """Anyone who cannot pay the next bid is folded. The leader stays in."""
    hi = room.highest_bid()
    leader = hi[0] if hi else None
    for c in room.players.values():
        if c.pid == leader:
            room.passed.discard(c.pid)
            continue
        if not can_raise(room, c.pid):
            room.passed.add(c.pid)


def lot_closed(room: "Room") -> bool:
    """True when nobody left can bid: sell to the leader, or unsold if there isn't one."""
    hi = room.highest_bid()
    if hi:
        return all(c.pid == hi[0] or c.pid in room.passed for c in room.players.values())
    return not any(can_raise(room, c.pid) and c.pid not in room.passed for c in room.players.values())


def all_have_minimum(room: "Room") -> bool:
    players = list(room.players.values())
    return bool(players) and all(len(c.squad) >= SQUAD_MIN for c in players)


class Room:
    def __init__(self, code: str):
        self.code = code
        self.players: dict[str, "Client"] = {}
        self.phase = "lobby"          # lobby/setup/draft/done
        self.batch: list[dict] = []
        self.queue: list[dict] = []
        self.current: dict | None = None
        self.last_pop: dict | None = None
        self.sold: list[dict] = []
        self.unsold: list[dict] = []
        self.bids: dict[str, float] = {}     # pid -> amount
        self.passed: set[str] = set()
        self.timer_handle: asyncio.TimerHandle | None = None
        self.deadline: float = 0.0
        self.lock = asyncio.Lock()
        self.ready_to_end = False
        self.close_after_lot = False
        self.end_votes: set[str] = set()
        self.results: dict | None = None

    def budget_of(self, pid: str) -> float:
        c = self.players.get(pid)
        return c.budget if c else 0.0

    def empty_slots(self, pid: str) -> int:
        c = self.players.get(pid)
        return SQUAD_MIN - len(c.squad) if c else SQUAD_MIN

    def max_bid(self, pid: str) -> float:
        """budget minus £1m reserve per empty slot beyond the one being bought now."""
        c = self.players.get(pid)
        if not c or len(c.squad) >= SQUAD_MAX:
            return 0.0
        empties = SQUAD_MIN - len(c.squad)
        reserve = SLOT_RESERVE * max(0, empties - 1)
        return round(max(0.0, c.budget - reserve), 2)

    def highest_bid(self) -> tuple[str, float] | None:
        if not self.bids:
            return None
        pid = max(self.bids, key=lambda k: (self.bids[k], self.players[k].budget - self.bids[k]))
        return pid, self.bids[pid]

    def state(self) -> dict:
        clients = list(self.players.values())
        hi = self.highest_bid()
        return {
            "code": self.code,
            "phase": self.phase,
            "players": [
                {
                    "id": c.pid, "name": c.name, "host": c.host, "budget": c.budget,
                    "squad_n": len(c.squad), "formation": c.formation,
                    "squad": c.squad, "assign": c.assign,
                    "is_you": False,
                }
                for c in clients
            ],
            "current": self.current,
            "high_bidder": hi[0] if hi else None,
            "high_bid": hi[1] if hi else None,
            "passed": sorted(self.passed),
            "sold": self.sold,
            "unsold": self.unsold,
            "max_bid": {c.pid: self.max_bid(c.pid) for c in clients},
            "deadline": self.deadline,
            "now": _now(),
            "squad_min": SQUAD_MIN,
            "squad_max": SQUAD_MAX,
            "short_of_xi": sum(1 for c in clients if len(c.squad) < SQUAD_MIN),
            "ready_to_end": self.ready_to_end,
            "end_votes": sorted(self.end_votes),
            "results": self.results if self.phase == "done" else None,
        }


def _now() -> float:
    return asyncio.get_event_loop().time()


class Client:
    def __init__(self, pid: str, name: str, ws: WebSocket, room: Room):
        self.pid = pid
        self.name = name
        self.ws = ws
        self.room = room
        self.host = False
        self.budget = START_BUDGET
        self.squad: list[dict] = []
        self.formation = "4-4-2"
        self.assign: dict[str, int] = {}   # player_id -> slot idx


ROOMS: dict[str, Room] = {}


async def broadcast(room: Room, event: dict):
    data = json.dumps(event)
    for c in list(room.players.values()):
        try:
            await asyncio.wait_for(c.ws.send_text(data), timeout=5)
        except Exception:
            pass


def score_xi(client: "Client", seat: int) -> dict:
    """Starting XI rating: fit for the slot they play, plus the back-three bonus on CBs."""
    slots = slots_for(client.formation)
    is_back3 = back3(client.formation)
    by_slot = {idx: pid for pid, idx in client.assign.items()}
    lines = []
    total = 0
    for i, slot in enumerate(slots):
        pid = by_slot.get(i)
        full = POOL_BY_ID.get(pid) if pid else None
        fit = int(full.get("fit", {}).get(slot["role"], 0)) if full else 0
        bonus = int(full.get("back3") or 0) if full and is_back3 and slot["role"] == "CB" else 0
        total += fit + bonus
        card = next((p for p in client.squad if p.get("id") == pid), None) if pid else None
        lines.append({
            "slot": slot["role"],
            "name": (card or {}).get("name") or (full or {}).get("name") or "Empty",
            "score": fit + bonus,
        })
    return {
        "id": client.pid,
        "name": client.name,
        "formation": client.formation,
        "total": total,
        "budget": client.budget,
        "seat": seat,
        "xi": lines,
    }


def build_results(room: "Room") -> dict:
    """Strict ranking. Combined starting-XI rating, then budget left, then who joined first."""
    table = [score_xi(c, i) for i, c in enumerate(room.players.values())]
    table.sort(key=lambda r: (-r["total"], -r["budget"], r["seat"], r["name"]))
    for i, row in enumerate(table):
        row["place"] = i + 1
        if i == 0:
            row["split"] = ""
            continue
        prev = table[i - 1]
        if row["total"] != prev["total"]:
            row["split"] = ""
        elif row["budget"] != prev["budget"]:
            row["split"] = "budget"
        else:
            row["split"] = "seat"
    if not table:
        return {"table": [], "winners": [], "losers": [], "forfeit": "Loser has to kiss Sid."}
    winner = table[0]["name"]
    loser = table[-1]["name"]
    return {
        "table": table,
        "winners": [winner],
        "losers": [loser],
        "forfeit": f"{loser} has to kiss Sid.",
    }


async def arm_end(room: Room):
    """Show the end button once every squad has 11. The auction keeps going."""
    if room.phase != "draft" or room.ready_to_end or not all_have_minimum(room):
        return
    room.ready_to_end = True
    await broadcast(room, {**state_event(room), "event": "xi_full"})


def state_event(room: Room) -> dict:
    return {"type": "state", **room.state()}


POOL_BY_ID = {p["id"]: p for p in POOL}


def refresh_assign(client: "Client") -> None:
    """Recompute slot assignment from hidden fits. Deterministic and stable."""
    if not client.squad:
        client.assign = {}
        return
    entries = []
    for card_in_squad in client.squad:
        full = POOL_BY_ID.get(card_in_squad["id"])
        if full:
            entries.append({"id": card_in_squad["id"], "ovr": full.get("ovr", 0), "fit": full.get("fit", {})})
        else:
            entries.append({"id": card_in_squad["id"], "ovr": 0, "fit": {}})
    try:
        client.assign = auto_assign(entries, client.formation)
    except Exception:
        # fallback: fill slots in order
        slots = slots_for(client.formation)
        client.assign = {card_in_squad["id"]: i for i, card_in_squad in enumerate(client.squad) if i < len(slots)}


def swap_slots(client: "Client", a: int, b: int) -> bool:
    slots = slots_for(client.formation)
    if a == b or not (0 <= a < len(slots)) or not (0 <= b < len(slots)):
        return False
    inv = {slot_idx: pid for pid, slot_idx in client.assign.items()}
    pa, pb = inv.get(a), inv.get(b)
    if pa is None and pb is None:
        return False
    if pa is not None:
        client.assign[pa] = b
    if pb is not None:
        client.assign[pb] = a
    return True


async def start_pop(room: Room):
    """Pop the next player. The end button appears at 11, but pops continue until every vote is in."""
    if room.phase != "draft":
        return
    if everyone_capped(room):
        await finish_draft(room, forced=True)
        return
    if room.close_after_lot or (room.ready_to_end and set(room.players) <= room.end_votes):
        await finish_draft(room)
        return
    if all_have_minimum(room):
        await arm_end(room)
    if room.close_after_lot or (room.ready_to_end and set(room.players) <= room.end_votes):
        await finish_draft(room)
        return
    if not room.queue:
        await finish_shortfall(room)
        return
    async with room.lock:
        room.current = room.queue.pop(0)
        room.last_pop = room.current
        room.bids = {}
        room.passed = set()
        auto_fold(room)
        closed = lot_closed(room)
        room.deadline = _now() + BID_WINDOW
        if room.timer_handle:
            room.timer_handle.cancel()
            room.timer_handle = None
        if not closed:
            room.timer_handle = asyncio.get_event_loop().call_later(BID_WINDOW, lambda: asyncio.ensure_future(resolve(room)))
    await broadcast(room, {**state_event(room), "event": "pop", "player": room.current})
    if closed:
        await resolve(room)


async def resolve(room: Room):
    """Timer expired or all passed — sell to highest bidder or mark unsold."""
    async with room.lock:
        if room.phase != "draft" or room.current is None:
            return  # already resolved (race guard)
        room.current = None          # race guard: second resolve becomes no-op
        hi = room.highest_bid()
        cur = room.last_pop
        room.last_pop = None
        if room.timer_handle:
            room.timer_handle.cancel()
            room.timer_handle = None
        if hi and cur:
            pid, amt = hi
            c = room.players[pid]
            c.budget = round(c.budget - amt, 2)
            c.squad.append(cur)
            refresh_assign(c)
            room.sold.append({**cur, "to": pid, "price": amt, "to_name": c.name})
            await broadcast(room, {**state_event(room), "event": "sold", "player": cur,
                                   "to": pid, "to_name": c.name, "price": amt})
        elif cur:
            room.unsold.append(cur)
            await broadcast(room, {**state_event(room), "event": "unsold", "player": cur})
    # lock released — next pop may call finish_draft safely
    await asyncio.sleep(1.2)
    await start_pop(room)


async def finish_shortfall(room: Room):
    """Pool ran out before every squad had 11. Fill from unsold, then open the vote if we can."""
    if not all_have_minimum(room):
        for c in room.players.values():
            need = SQUAD_MIN - len(c.squad)
            while need > 0 and room.unsold:
                fa = room.unsold.pop(0)
                c.squad.append(fa)
                refresh_assign(c)
                need -= 1
    if all_have_minimum(room):
        await arm_end(room)


async def finish_draft(room: Room, forced: bool = False):
    if room.phase == "done":
        return
    unanimous = room.ready_to_end and not (set(room.players) - room.end_votes)
    if not forced and not everyone_capped(room) and not unanimous:
        return
    room.results = build_results(room)
    room.phase = "done"
    if room.timer_handle:
        room.timer_handle.cancel()
        room.timer_handle = None
    room.current = None
    room.queue = []
    await broadcast(room, {**state_event(room), "event": "done"})


@app.get("/")
async def index():
    return FileResponse(BASE / "index.html")


@app.get("/pool-summary")
async def pool_summary():
    return [{"id": p["id"], "name": p["name"], "pos": p["pos"], "nat": p["nat"], "club": p["club"],
             "era": p["era"], "ht": p["ht"], "wt": p["wt"], "pace": p["pace"], "note": p["note"]} for p in POOL]


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    client: Client | None = None
    room: Room | None = None
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            t = msg.get("type")

            if t == "create":
                code = new_code()
                while code in ROOMS:
                    code = new_code()
                room = Room(code)
                ROOMS[code] = room
                pid = new_id()
                client = Client(pid, msg.get("name", "Host")[:18], ws, room)
                client.host = True
                room.players[pid] = client
                await ws.send_text(json.dumps({"type": "joined", "code": code, "pid": pid,
                                               "formations": FORMATION_NAMES}))
                await broadcast(room, state_event(room))

            elif t == "join":
                code = msg.get("code", "").upper().strip()
                room = ROOMS.get(code)
                if not room:
                    await ws.send_text(json.dumps({"type": "error", "msg": "Room not found"}))
                    continue
                if room.phase != "lobby":
                    # reconnect path
                    match = [c for c in room.players.values() if c.name == msg.get("name", "")]
                    if match:
                        client = match[0]
                        client.ws = ws
                        await ws.send_text(json.dumps({"type": "joined", "code": code, "pid": client.pid,
                                                       "formations": FORMATION_NAMES, "reconnect": True}))
                        await ws.send_text(json.dumps(state_event(room)))
                    else:
                        await ws.send_text(json.dumps({"type": "error", "msg": "Draft already started"}))
                    continue
                # refresh-safe: same name rejoining the lobby reattaches instead of duplicating
                match = [c for c in room.players.values() if c.name == msg.get("name", "")]
                if match:
                    client = match[0]
                    client.ws = ws
                    await ws.send_text(json.dumps({"type": "joined", "code": code, "pid": client.pid,
                                                   "formations": FORMATION_NAMES, "reconnect": True}))
                    await broadcast(room, state_event(room))
                    continue
                pid = new_id()
                client = Client(pid, msg.get("name", "Player")[:18], ws, room)
                room.players[pid] = client
                await ws.send_text(json.dumps({"type": "joined", "code": code, "pid": pid,
                                               "formations": FORMATION_NAMES}))
                await broadcast(room, state_event(room))

            elif t == "set_formation" and client:
                if msg.get("formation") in FORMATION_NAMES:
                    client.formation = msg["formation"]
                    await broadcast(room, state_event(room))

            elif t == "start" and client and client.host and room.phase == "lobby":
                if len(room.players) < 2:
                    await ws.send_text(json.dumps({"type": "error", "msg": "Need at least 2 players"}))
                    continue
                room.phase = "draft"
                queue = draw_queue(room)
                room.batch = queue
                room.queue = list(queue)
                random.shuffle(room.queue)
                await broadcast(room, {**state_event(room), "event": "draft_start"})
                await start_pop(room)

            elif t == "bid" and client and room.phase == "draft" and room.current:
                amt = round(float(msg.get("amount", 0)), 2)
                cur = room.current
                hi = room.highest_bid()
                cap = client.budget
                # budget cap including reserve rule
                if len(client.squad) >= SQUAD_MAX:
                    await ws.send_text(json.dumps({"type": "error", "msg": "Squad is full — 15 is the limit"}))
                    continue
                if amt > room.max_bid(client.pid) + 0.001:
                    await ws.send_text(json.dumps({"type": "error",
                        "msg": f"Over budget cap (£{room.max_bid(client.pid):.1f} max now)"}))
                    continue
                if not hi:
                    if amt < MIN_OPEN - 0.001:
                        await ws.send_text(json.dumps({"type": "error", "msg": "Opening bid is £1m"}))
                        continue
                else:
                    hid, hamt = hi
                    if hid == client.pid:
                        continue  # already highest
                    if amt < hamt + MIN_RAISE - 0.001:
                        await ws.send_text(json.dumps({"type": "error",
                            "msg": f"Minimum raise is £{MIN_RAISE:.1f}"}))
                        continue
                room.bids[client.pid] = amt
                room.passed.discard(client.pid)
                auto_fold(room)
                if lot_closed(room):
                    if room.timer_handle:
                        room.timer_handle.cancel()
                        room.timer_handle = None
                    await broadcast(room, {**state_event(room), "event": "bid",
                                           "by": client.pid, "by_name": client.name, "amount": amt})
                    await resolve(room)
                    continue
                room.deadline = _now() + RESET_WINDOW
                if room.timer_handle:
                    room.timer_handle.cancel()
                room.timer_handle = asyncio.get_event_loop().call_later(
                    RESET_WINDOW, lambda: asyncio.ensure_future(resolve(room)))
                await broadcast(room, {**state_event(room), "event": "bid",
                                       "by": client.pid, "by_name": client.name, "amount": amt})

            elif t == "pass" and client and room.phase == "draft" and room.current:
                if client.pid == (room.highest_bid() or (None,))[0]:
                    continue
                room.passed.add(client.pid)
                auto_fold(room)
                await broadcast(room, {**state_event(room), "event": "pass", "by": client.pid})
                if lot_closed(room):
                    if room.timer_handle:
                        room.timer_handle.cancel()
                        room.timer_handle = None
                    await resolve(room)

            elif t == "move" and client:
                # drag or tap: {player_id, slot} — move that player to slot, swap occupant
                try:
                    dest = int(msg["slot"])
                except (KeyError, TypeError, ValueError):
                    continue
                slots = slots_for(client.formation)
                if not (0 <= dest < len(slots)):
                    continue
                pid_moved = msg.get("player_id")
                inv = {slot_idx: p for p, slot_idx in client.assign.items()}
                occupant = inv.get(dest)
                src = client.assign.get(pid_moved)
                if src is None:
                    # unassigned squad member dragged onto a slot — place if free/swap
                    if pid_moved not in [p.get("id") for p in client.squad]:
                        continue
                    client.assign[pid_moved] = dest
                    if occupant is not None and occupant != pid_moved:
                        # displaced occupant loses its slot (stays in squad, unassigned)
                        client.assign.pop(occupant, None)
                else:
                    if occupant is not None and occupant != pid_moved:
                        client.assign[occupant] = src
                    client.assign[pid_moved] = dest
                await broadcast(room, {**state_event(room)})

            elif t == "swap" and client:
                try:
                    ok = swap_slots(client, int(msg["a"]), int(msg["b"]))
                except (KeyError, TypeError, ValueError):
                    ok = False
                if ok:
                    await broadcast(room, {**state_event(room)})

            elif t == "set_formation_draft" and client and room.phase == "draft":
                if msg.get("formation") in FORMATION_NAMES:
                    client.formation = msg["formation"]
                    refresh_assign(client)
                    await broadcast(room, state_event(room))

            elif t == "end_vote" and client and room and room.phase == "draft" and room.ready_to_end:
                room.end_votes.add(client.pid)
                if set(room.players) <= room.end_votes:
                    if room.current is not None:
                        room.close_after_lot = True
                        await broadcast(room, {**state_event(room), "event": "end_vote", "by": client.pid})
                    else:
                        await finish_draft(room)
                else:
                    await broadcast(room, {**state_event(room), "event": "end_vote", "by": client.pid})

            elif t == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if room and client:
            # keep client in room for reconnect; just mark socket dead
            client.ws = None
