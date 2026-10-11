from __future__ import annotations

import asyncio
import json
import random
import secrets
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
app = FastAPI(title="3-2-1 Diwali")
SUITS = ["S", "H", "D", "C"]
SYMBOL = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
RANKS = [("A", 14)] + [(str(value), value) for value in range(2, 11)] + [("J", 11), ("Q", 12), ("K", 13)]
GROUP_SIZES = {"1": 1, "2": 2, "3": 3}


def new_id(prefix: str = "p") -> str:
    return prefix + secrets.token_urlsafe(8).replace("-", "").replace("_", "")


def new_code() -> str:
    return "".join(random.choice(string.ascii_uppercase) for _ in range(4))


def make_deck() -> list[dict[str, Any]]:
    return [
        {"id": f"{rank}{suit}", "rank": rank, "value": value, "suit": suit,
         "label": f"{rank}{SYMBOL[suit]}", "red": suit in ("H", "D")}
        for rank, value in RANKS for suit in SUITS
    ]


@dataclass
class Player:
    id: str
    name: str
    host: bool = False
    connected: bool = False
    ws: WebSocket | None = None
    hand: list[dict[str, Any]] = field(default_factory=list)
    groups: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: {"1": [], "2": [], "3": []})
    locked: bool = False
    score: float = 0.0
    group_shares: float = 0.0
    money: float = 0.0


@dataclass
class Room:
    code: str
    host_id: str
    players: dict[str, Player] = field(default_factory=dict)
    phase: str = "lobby"
    hand_number: int = 0
    round_message: str = "Waiting for the host to start the game."
    group_results: list[dict[str, Any]] = field(default_factory=list)
    revealed_groups: list[dict[str, Any]] = field(default_factory=list)
    group_shares: dict[str, float] = field(default_factory=dict)
    set_deltas: dict[str, float] = field(default_factory=dict)
    money_value: float = 0.0
    money_deltas: dict[str, float] = field(default_factory=dict)
    hand_winner_ids: list[str] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def player_list(self) -> list[Player]:
        return list(self.players.values())

    def state_for(self, viewer_id: str) -> dict[str, Any]:
        viewer = self.players.get(viewer_id)
        return {
            "type": "state",
            "room": self.code,
            "viewer": viewer_id,
            "phase": self.phase,
            "hand_number": self.hand_number,
            "round_message": self.round_message,
            "is_host": viewer_id == self.host_id,
            "your_hand": viewer.hand if viewer else [],
            "your_groups": viewer.groups if viewer else {"1": [], "2": [], "3": []},
            "your_locked": viewer.locked if viewer else False,
            "group_results": self.group_results if self.phase == "results" else [],
            "revealed_groups": self.revealed_groups if self.phase == "results" else [],
            "hand_winner_ids": self.hand_winner_ids if self.phase == "results" else [],
            "set_deltas": self.set_deltas if self.phase == "results" else {},
            "money_value": self.money_value,
            "money_deltas": self.money_deltas if self.phase == "results" else {},
            "players": [
                {
                    "id": p.id,
                    "name": p.name,
                    "host": p.host,
                    "connected": p.connected,
                    "locked": p.locked,
                    "score": p.score,
                    "group_shares": p.group_shares,
                    "money": p.money,
                }
                for p in self.player_list
            ],
        }


rooms: dict[str, Room] = {}
rooms_lock = asyncio.Lock()


class NameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=18)


class CreateResponse(BaseModel):
    room: str
    player_id: str


async def get_room(code: str) -> Room:
    room = rooms.get(code.upper())
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


def clean_name(name: str) -> str:
    return " ".join(name.strip().split())[:18]


@app.get("/", response_class=FileResponse)
async def index() -> FileResponse:
    return FileResponse(BASE / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "diwali321", "rules": "six-cards-1-2-3-groups"}


@app.post("/api/rooms", response_model=CreateResponse)
async def create_room(payload: NameRequest) -> CreateResponse:
    name = clean_name(payload.name)
    if not name:
        raise HTTPException(status_code=400, detail="Enter a name")
    async with rooms_lock:
        code = new_code()
        while code in rooms:
            code = new_code()
        pid = new_id()
        room = Room(code=code, host_id=pid)
        room.players[pid] = Player(id=pid, name=name, host=True)
        rooms[code] = room
    return CreateResponse(room=code, player_id=pid)


@app.post("/api/rooms/{code}/join", response_model=CreateResponse)
async def join_room(code: str, payload: NameRequest) -> CreateResponse:
    code = code.upper().strip()
    name = clean_name(payload.name)
    if not name:
        raise HTTPException(status_code=400, detail="Enter a name")
    room = await get_room(code)
    async with room.lock:
        if room.phase != "lobby":
            raise HTTPException(status_code=409, detail="That game has already started")
        if len(room.players) >= 8:
            raise HTTPException(status_code=409, detail="Room is full (8 players maximum)")
        if any(p.name.casefold() == name.casefold() for p in room.player_list):
            raise HTTPException(status_code=409, detail="That name is already in this room")
        pid = new_id()
        room.players[pid] = Player(id=pid, name=name)
    return CreateResponse(room=code, player_id=pid)


async def broadcast(room: Room) -> None:
    dead: list[str] = []
    for pid, player in list(room.players.items()):
        if player.ws is None:
            continue
        try:
            await player.ws.send_json(room.state_for(pid))
        except Exception:
            dead.append(pid)
    for pid in dead:
        room.players[pid].connected = False
        room.players[pid].ws = None


def deal_hand(room: Room) -> None:
    room.hand_number += 1
    room.phase = "arranging"
    room.group_results = []
    room.revealed_groups = []
    room.group_shares = {}
    room.set_deltas = {}
    room.money_deltas = {}
    room.hand_winner_ids = []
    deck = make_deck()
    random.shuffle(deck)
    for player in room.player_list:
        player.hand = [deck.pop() for _ in range(6)]
        player.groups = {"1": [], "2": [], "3": []}
        player.locked = False
    room.round_message = f"Set {room.hand_number}: arrange your six cards into groups of 1, 2, and 3."


def resolve_hand(room: Room) -> None:
    room.group_results = []
    room.revealed_groups = []
    room.group_shares = {p.id: 0.0 for p in room.player_list}
    for player in room.player_list:
        room.revealed_groups.append({"player_id": player.id, "name": player.name, "groups": player.groups})
    for group in ("1", "2", "3"):
        scores = {p.id: sum(c["value"] for c in p.groups[group]) for p in room.player_list}
        best = max(scores.values())
        winners = [pid for pid, score in scores.items() if score == best]
        share = 1.0 / len(winners)
        shares = {pid: (share if pid in winners else 0.0) for pid in scores}
        for pid, player_share in shares.items():
            room.group_shares[pid] += player_share
        room.group_results.append({"group": int(group), "scores": scores, "winners": winners, "shares": shares})
    benchmark = len(room.players) and 3.0 / len(room.players)
    room.set_deltas = {pid: shares - benchmark for pid, shares in room.group_shares.items()}
    room.money_deltas = {
        pid: round(delta * room.money_value, 2)
        for pid, delta in room.set_deltas.items()
    }
    for player in room.player_list:
        player.group_shares += room.group_shares[player.id]
        player.score += room.set_deltas[player.id]
        player.money += room.money_deltas[player.id]
    best_groups = max(room.group_shares.values())
    room.hand_winner_ids = [pid for pid, shares in room.group_shares.items() if shares == best_groups]
    deltas = ", ".join(
        f"{room.players[pid].name} {'+' if delta > 0 else ''}{delta:g}"
        for pid, delta in room.set_deltas.items()
    )
    room.round_message = f"Set {room.hand_number} settled: {deltas}."
    room.phase = "results"


async def handle_action(room: Room, pid: str, action: dict[str, Any]) -> str | None:
    player = room.players.get(pid)
    if not player:
        return "Player not found"
    kind = action.get("action")

    if kind == "start":
        if pid != room.host_id:
            return "Only the host can start"
        if room.phase != "lobby":
            return "The game has already started"
        if len(room.players) < 2:
            return "Invite at least one friend first"
        try:
            money_value = float(action.get("money_value"))
        except (TypeError, ValueError):
            return "Enter the money value per point"
        if not 0 < money_value <= 1_000_000_000:
            return "Money value must be greater than zero"
        room.money_value = round(money_value, 2)
        deal_hand(room)
        return None

    if kind == "lock":
        if room.phase != "arranging":
            return "This set is already locked"
        if player.locked:
            return "Your arrangement is already locked"
        raw_groups = action.get("groups")
        if not isinstance(raw_groups, dict):
            return "Send groups 1, 2, and 3"
        groups: dict[str, list[dict[str, Any]]] = {}
        hand_by_id = {card["id"]: card for card in player.hand}
        used: list[str] = []
        for group, expected_size in GROUP_SIZES.items():
            ids = raw_groups.get(group)
            if not isinstance(ids, list) or len(ids) != expected_size:
                return f"Group {group} needs exactly {expected_size} card{'s' if expected_size != 1 else ''}"
            if any(not isinstance(card_id, str) or card_id not in hand_by_id for card_id in ids):
                return "Every card must come from your hand"
            used.extend(ids)
            groups[group] = [hand_by_id[card_id] for card_id in ids]
        if len(set(used)) != 6:
            return "Use each card exactly once"
        player.groups = groups
        player.locked = True
        if all(p.locked for p in room.player_list):
            resolve_hand(room)
        else:
            room.round_message = f"{player.name} is locked in. Waiting for the other players."
        return None

    if kind == "next_hand":
        if pid != room.host_id:
            return "Only the host can deal again"
        if room.phase != "results":
            return "Finish the current set first"
        deal_hand(room)
        return None

    if kind == "reset":
        if pid != room.host_id:
            return "Only the host can restart"
        room.phase = "lobby"
        room.hand_number = 0
        room.round_message = "Waiting for the host to start the game."
        room.group_results = []
        room.revealed_groups = []
        room.group_shares = {}
        room.set_deltas = {}
        room.money_value = 0.0
        room.money_deltas = {}
        room.hand_winner_ids = []
        for p in room.player_list:
            p.hand = []
            p.groups = {"1": [], "2": [], "3": []}
            p.locked = False
            p.score = 0.0
            p.group_shares = 0.0
            p.money = 0.0
        return None

    return "Unknown action"


@app.websocket("/ws/{code}/{pid}")
async def websocket_endpoint(websocket: WebSocket, code: str, pid: str) -> None:
    room = rooms.get(code.upper())
    if room is None or pid not in room.players:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    player = room.players[pid]
    async with room.lock:
        player.ws = websocket
        player.connected = True
        await broadcast(room)
    try:
        while True:
            data = await websocket.receive_json()
            async with room.lock:
                error = await handle_action(room, pid, data)
                if error:
                    await websocket.send_json({"type": "error", "message": error})
                else:
                    await broadcast(room)
    except WebSocketDisconnect:
        async with room.lock:
            if player.ws is websocket:
                player.ws = None
                player.connected = False
                await broadcast(room)
    except Exception:
        async with room.lock:
            if player.ws is websocket:
                player.ws = None
                player.connected = False
                await broadcast(room)
