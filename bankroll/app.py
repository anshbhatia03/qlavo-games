"""Bankroll HTTP/WebSocket transport.

All gameplay decisions are delegated to game_engine.GameEngine. This module owns
rooms, websocket connections, reconnect flags, and bot scheduling only.
"""
from __future__ import annotations

import asyncio
import secrets
import string
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from bot_policy import BotPolicy
from game_engine import GameEngine, GameState, RuleError

BASE = Path(__file__).parent
app = FastAPI(title="Bankroll")


@dataclass
class Room:
    code: str
    engine: GameEngine = field(default_factory=GameEngine)
    state: GameState | None = None
    players: dict[str, dict[str, Any]] = field(default_factory=dict)
    sockets: dict[str, WebSocket] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_activity: float = field(default_factory=time.monotonic)

    def specs(self) -> list[dict[str, Any]]:
        return list(self.players.values())


rooms: dict[str, Room] = {}
rooms_lock = asyncio.Lock()
ROOM_TTL_SECONDS = 12 * 60 * 60


class NameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=18)


class StartRequest(BaseModel):
    target: int = 3000
    limit: int = 0


class BotRequest(BaseModel):
    difficulty: str = "normal"
    player_id: str


class LeaveRequest(BaseModel):
    player_id: str


def clean_name(name: str) -> str:
    return " ".join(name.strip().split())[:18]


def new_id(prefix: str = "p") -> str:
    return prefix + secrets.token_urlsafe(8).replace("-", "").replace("_", "")


def new_code() -> str:
    return "".join(secrets.choice(string.ascii_uppercase) for _ in range(4))


async def get_room(code: str) -> Room:
    room = rooms.get(code.upper())
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@app.get("/", response_class=FileResponse)
async def index() -> FileResponse:
    return FileResponse(BASE / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "bankroll", "engine": "authoritative-v1", "tiles": str(len(GameEngine().board_data))}


@app.get("/api/rooms/{code}/session/{pid}")
async def session_status(code: str, pid: str) -> dict[str, Any]:
    room = await get_room(code)
    if pid not in room.players:
        raise HTTPException(status_code=404, detail="Player not found")
    return {"valid": True, "phase": room.state.phase.lower() if room.state else "lobby"}


@app.post("/api/rooms")
async def create_room(payload: NameRequest) -> dict[str, str]:
    name = clean_name(payload.name)
    if not name:
        raise HTTPException(status_code=422, detail="Name cannot be blank")
    async with rooms_lock:
        now = time.monotonic()
        for stale_code, stale_room in list(rooms.items()):
            if not stale_room.sockets and now - stale_room.last_activity > ROOM_TTL_SECONDS:
                rooms.pop(stale_code, None)
        code = new_code()
        while code in rooms:
            code = new_code()
        pid = new_id()
        rooms[code] = Room(code=code, players={pid: {"id": pid, "username": name, "isBot": False}})
    return {"room": code, "player_id": pid}


@app.post("/api/rooms/{code}/join")
async def join_room(code: str, payload: NameRequest) -> dict[str, str]:
    room = await get_room(code)
    async with room.lock:
        if room.state is not None:
            raise HTTPException(status_code=409, detail="Game already started")
        if len(room.players) >= 4:
            raise HTTPException(status_code=409, detail="Table is full (max 4)")
        name = clean_name(payload.name)
        if not name:
            raise HTTPException(status_code=422, detail="Name cannot be blank")
        if any(p["username"].casefold() == name.casefold() for p in room.players.values()):
            raise HTTPException(status_code=409, detail="Name already taken")
        pid = new_id()
        room.players[pid] = {"id": pid, "username": name, "isBot": False}
        room.last_activity = time.monotonic()
    return {"room": room.code, "player_id": pid}


@app.post("/api/rooms/{code}/bots")
async def add_bot(code: str, payload: BotRequest) -> dict[str, str]:
    room = await get_room(code)
    async with room.lock:
        if room.state is not None:
            raise HTTPException(status_code=409, detail="Game already started")
        if len(room.players) >= 4:
            raise HTTPException(status_code=409, detail="Table is full")
        if payload.player_id != next(iter(room.players)):
            raise HTTPException(status_code=403, detail="Only the host can add bots")
        difficulty = payload.difficulty.lower()
        if difficulty not in {"easy", "normal", "hard"}:
            raise HTTPException(status_code=400, detail="difficulty must be easy, normal or hard")
        pid = new_id("bot")
        count = sum(1 for p in room.players.values() if p["isBot"])
        room.players[pid] = {"id": pid, "username": f"Bot {count + 1}", "isBot": True, "difficulty": difficulty}
        room.last_activity = time.monotonic()
    return {"room": room.code, "player_id": pid}


@app.post("/api/rooms/{code}/leave")
async def leave_room(code: str, payload: LeaveRequest) -> dict[str, bool]:
    room = await get_room(code)
    socket_to_close: WebSocket | None = None
    async with room.lock:
        if payload.player_id not in room.players:
            raise HTTPException(status_code=404, detail="Player not found")
        if room.state is not None:
            return {"removed": False}
        room.players.pop(payload.player_id)
        socket_to_close = room.sockets.pop(payload.player_id, None)
        room.last_activity = time.monotonic()
        await broadcast(room)
    if socket_to_close:
        asyncio.create_task(close_replaced_socket(socket_to_close))
    if not room.players:
        async with rooms_lock:
            rooms.pop(room.code, None)
    return {"removed": True}


def lobby_snapshot(room: Room, viewer_id: str) -> dict[str, Any]:
    board = []
    city_group_sizes: dict[str, int] = {}
    public_count = sum(1 for x in room.engine.board_data if x["kind"] == "public")
    for raw in room.engine.board_data:
        if raw.get("colorGroup"):
            city_group_sizes[raw["colorGroup"]] = city_group_sizes.get(raw["colorGroup"], 0) + 1
    for raw in room.engine.board_data:
        base_rent = raw.get("baseRent", 0)
        board.append({"id": raw["id"], "kind": raw["kind"], "name": raw["name"], "color": raw.get("colorGroup"), "colorGroup": raw.get("colorGroup"), "price": raw.get("purchasePrice", 0), "purchasePrice": raw.get("purchasePrice", 0), "rent": base_rent, "baseRent": base_rent, "rentOwned2": raw.get("rentOwned2", raw.get("rentWithSet", base_rent)), "rentWithSet": raw.get("rentWithSet", base_rent), "rentBuilding1": raw.get("rentBuilding1", 0), "rentBuilding2": raw.get("rentBuilding2", 0), "rentBuilding3": raw.get("rentBuilding3", 0), "rentByOwnedCount": raw.get("rentByOwnedCount", []), "currentRent": base_rent, "ownedCount": 0, "setSize": city_group_sizes.get(raw.get("colorGroup"), public_count if raw["kind"] == "public" else 0), "buildingPrice": raw.get("buildingPrice", 0), "ownerId": None, "buildingLevel": 0, "icon": raw.get("icon", "")})
    first = next(iter(room.players), None)
    start_position = next((i for i, raw in enumerate(room.engine.board_data) if raw.get("kind") == "start"), 0)
    return {"type": "state", "phase": "lobby", "enginePhase": "LOBBY", "room": room.code, "viewer": viewer_id, "is_host": viewer_id == first, "target_worth": 3000, "round_limit": 0, "round_number": 0, "current_id": first, "current_name": room.players[first]["username"] if first else "", "last_roll": None, "pending_move": False, "pending_property": None, "pending_lose": None, "auction": None, "trade": None, "winner_id": None, "win_reason": "", "board": board, "log": ["Waiting for the host to start."], "players": [{"id": p["id"], "name": p["username"], "username": p["username"], "host": p["id"] == first, "connected": p["id"] in room.sockets or p["isBot"], "isBot": p["isBot"], "pos": start_position, "cash": 0, "net_worth": 0, "jailed": 0, "properties": []} for p in room.players.values()], "you": None}


async def broadcast(room: Room) -> None:
    dead: list[str] = []
    for pid, ws in list(room.sockets.items()):
        try:
            payload = room.engine.snapshot(room.state, pid) if room.state is not None else lobby_snapshot(room, pid)
            payload["room"] = room.code
            payload["is_host"] = pid == next(iter(room.players), None)
            await ws.send_json(payload)
        except Exception:
            dead.append(pid)
    for pid in dead:
        room.sockets.pop(pid, None)
        if room.state and pid in room.state.players:
            room.state.players[pid].connected = False


async def close_replaced_socket(websocket: WebSocket) -> None:
    try:
        await websocket.close(code=4001, reason="Reconnected elsewhere")
    except Exception:
        pass


async def run_bots(room: Room) -> None:
    """Advance autonomous bot seats until a human decision is needed."""
    if room.state is None:
        return
    for _ in range(80):
        state = room.state
        if state.phase == "GAME_OVER":
            return
        # Auction: bots list, bid, opt out, and settle while a human initiator waits.
        if state.auction:
            auction = state.auction
            policy = BotPolicy("normal")
            acted = False
            for p in state.players.values():
                if not p.is_bot or p.bankrupt or p.forfeited or p.id in auction.opted_out:
                    continue
                action = policy.choose(room.engine, state, p)
                if action.get("type") == "END_TURN":
                    continue
                try:
                    room.engine.apply(state, p.id, action)
                    await broadcast(room)
                    await asyncio.sleep(0.18)
                    acted = True
                except RuleError:
                    continue
            humans_pending = [p for p in state.players.values()
                              if not p.is_bot and not p.bankrupt and not p.forfeited
                              and p.id not in auction.opted_out
                              and (not auction.listings or any(not l.bids for l in auction.listings))]
            # Watchdog: close the auction once everyone has passed.
            active_others = [p for p in state.players.values() if p.id != auction.initiator_id and not p.bankrupt and not p.forfeited]
            all_out = all(p.id in auction.opted_out for p in active_others) if active_others else True
            no_external_bids = all(
                (not l.bids) or all(bidder == l.seller_id for bidder in l.bids)
                for l in auction.listings)
            seller_is_bot_or_out = all(
                l.seller_id in auction.opted_out or state.players[l.seller_id].is_bot
                for l in auction.listings)
            if ((all_out or not auction.listings or (no_external_bids and seller_bot_or_out)) and acted is False):
                auction.quiet_cycles += 1
                if auction.quiet_cycles >= 3:
                    current = room.engine.current_player(state)
                    room.engine._emit(state, "AUCTION_CANCELLED", current.id, text="Everyone passed — Auction closed.")
                    state.auction = None
                    room.engine._after_landing(state, current)
                    await broadcast(room)
                    continue
            else:
                auction.quiet_cycles = 0
            # Nobody could act and the watchdog has not fired yet: count a quiet cycle too.
            if not acted:
                auction.quiet_cycles += 1
            if humans_pending:
                return  # wait for the human decision
            if acted:
                continue
        player = room.engine.current_player(state)
        if not player.is_bot:
            return
        difficulty = next((x.get("difficulty", "normal") for x in room.players.values() if x["id"] == player.id), "normal")
        action = BotPolicy(difficulty).choose(room.engine, state, player)
        try:
            room.engine.apply(state, player.id, action)
            await broadcast(room)
            await asyncio.sleep(0.32 if action.get("type") == "ROLL_DICE" else 0.14)
        except RuleError:
            # A bot fallback is deliberately conservative and still goes through the engine.
            if state.pending_property_id:
                room.engine.apply(state, player.id, {"type": "SKIP_PROPERTY", "propertyId": state.pending_property_id})
            elif state.pending_card and player.properties_owned:
                room.engine.apply(state, player.id, {"type": "CHOOSE_LOST_PROPERTY", "propertyId": next(iter(player.properties_owned))})
            elif state.turn_phase == "TURN_END":
                room.engine.apply(state, player.id, {"type": "END_TURN"})
            else:
                return
    await broadcast(room)


async def start_room(room: Room, target: int, limit: int) -> None:
    room.state = room.engine.new_game(room.specs(), target, limit)
    for p in room.state.players.values():
        p.connected = p.id in room.sockets or p.is_bot
    await run_bots(room)


@app.websocket("/ws/{code}/{pid}")
async def websocket_endpoint(websocket: WebSocket, code: str, pid: str) -> None:
    room = rooms.get(code.upper())
    if room is None or pid not in room.players:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    async with room.lock:
        previous = room.sockets.get(pid)
        room.sockets[pid] = websocket
        room.last_activity = time.monotonic()
        if room.state and pid in room.state.players:
            room.state.players[pid].connected = True
        await broadcast(room)
    if previous and previous is not websocket:
        asyncio.create_task(close_replaced_socket(previous))
    try:
        while True:
            data = await websocket.receive_json()
            async with room.lock:
                if room.sockets.get(pid) is not websocket:
                    await websocket.close(code=4001, reason="Reconnected elsewhere")
                    return
                if not isinstance(data, dict):
                    await websocket.send_json({"type": "error", "message": "Action must be an object"})
                    continue
                room.last_activity = time.monotonic()
                if room.state is None:
                    requested = data.get("type") or data.get("action")
                    if requested not in {"START_GAME", "start"}:
                        await websocket.send_json({"type": "error", "message": "Waiting for host"})
                    elif pid != next(iter(room.players)):
                        await websocket.send_json({"type": "error", "message": "Only host can start"})
                    elif len(room.players) < 2:
                        await websocket.send_json({"type": "error", "message": "Add at least one opponent or bot"})
                    else:
                        try:
                            await start_room(room, int(data.get("target", 3000)), int(data.get("limit", 0)))
                        except (RuleError, ValueError) as exc:
                            await websocket.send_json({"type": "error", "message": str(exc)})
                else:
                    try:
                        # Backwards-compatible lobby action from the current client.
                        if data.get("action") == "start":
                            raise RuleError("Game already started")
                        elif data.get("action") == "next_game":
                            if pid != next(iter(room.players)):
                                raise RuleError("Only host can restart")
                            if room.state.phase != "GAME_OVER":
                                raise RuleError("Game is still in progress")
                            await start_room(room, room.state.target_worth, room.state.round_limit)
                        else:
                            action = dict(data)
                            if "action" in action and "type" not in action:
                                action["type"] = {"roll": "ROLL_DICE", "confirm_move": "ROLL_DICE", "buy_property": "BUY_PROPERTY", "end_turn": "END_TURN", "build": "UPGRADE_PROPERTY", "sell_property": "SELL_PROPERTY"}.get(action["action"], action["action"])
                            room.engine.apply(room.state, pid, action)
                            await broadcast(room)
                            await run_bots(room)
                    except (RuleError, ValueError, KeyError) as exc:
                        await websocket.send_json({"type": "error", "message": str(exc)})
                await broadcast(room)
    except WebSocketDisconnect:
        async with room.lock:
            if room.sockets.get(pid) is websocket:
                room.sockets.pop(pid, None)
                if room.state and pid in room.state.players:
                    room.state.players[pid].connected = False
                await broadcast(room)
    except Exception:
        async with room.lock:
            if room.sockets.get(pid) is websocket:
                room.sockets.pop(pid, None)
                if room.state and pid in room.state.players:
                    room.state.players[pid].connected = False
                await broadcast(room)
