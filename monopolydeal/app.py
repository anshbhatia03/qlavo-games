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
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from game_engine import GameEngine, GameState, RuleError, SUPER_ADMIN_NAMES, is_super_admin, make_deck

BASE = Path(__file__).parent
app = FastAPI(title="Monopoly Deal — Qlavo")
app.mount("/assets", StaticFiles(directory=BASE / "static"), name="assets")
ROOM_TTL = 12 * 60 * 60


def new_id(prefix: str = "p") -> str:
    return prefix + secrets.token_urlsafe(8).replace("-", "").replace("_", "")


def new_code() -> str:
    return "".join(secrets.choice(string.ascii_uppercase) for _ in range(4))


def clean_name(name: str) -> str:
    return " ".join(name.strip().split())[:24]


@dataclass
class Room:
    code: str
    players: dict[str, dict[str, Any]] = field(default_factory=dict)
    sockets: dict[str, WebSocket] = field(default_factory=dict)
    state: GameState | None = None
    engine: GameEngine = field(default_factory=GameEngine)
    last_activity: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


rooms: dict[str, Room] = {}
rooms_lock = asyncio.Lock()


class NameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class LeaveRequest(BaseModel):
    player_id: str


async def get_room(code: str) -> Room:
    room = rooms.get(code.upper().strip())
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


def lobby_snapshot(room: Room, viewer_id: str) -> dict[str, Any]:
    return {
        "type": "state", "phase": "lobby", "room": room.code, "viewer": viewer_id,
        "viewer_name": room.players[viewer_id]["username"], "is_host": viewer_id == next(iter(room.players), None),
        "private_viewer": is_super_admin(room.players[viewer_id]["username"]), "current_id": None,
        "current_name": "", "turn_number": 0, "plays_left": None, "draw_count": 106,
        "discard_count": 0, "discard_top": None, "last_play": None, "your_hand": [], "your_bank": [], "your_properties": [], "your_buildings": [], "your_complete_sets": [],
        "players": [{"id": p["id"], "name": p["username"], "host": p["id"] == next(iter(room.players), None),
                     "connected": p["id"] in room.sockets, "hand_count": 0, "bank_total": 0, "bank": [], "properties": [], "complete_sets": []}
                    for p in room.players.values()],
        "events": ["Waiting for the host to deal five cards."], "winner_id": None, "pending": None,
    }


async def broadcast(room: Room) -> None:
    dead: list[str] = []
    for pid, ws in list(room.sockets.items()):
        try:
            payload = lobby_snapshot(room, pid) if room.state is None else room.engine.snapshot(room.state, pid)
            payload["room"] = room.code
            await ws.send_json(payload)
        except Exception:
            dead.append(pid)
    for pid in dead:
        if room.sockets.get(pid):
            room.sockets.pop(pid, None)
        if room.state and pid in room.state.players:
            room.state.players[pid].connected = False


async def close_old(ws: WebSocket) -> None:
    try:
        await ws.close(code=4001, reason="Reconnected elsewhere")
    except Exception:
        pass


@app.get("/", response_class=FileResponse)
async def index() -> FileResponse:
    return FileResponse(BASE / "index.html", headers={"Cache-Control": "no-store, max-age=0"})


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "monopolydeal", "deck_total": 110, "playable_cards": len(make_deck()), "players_per_room": "2-5", "authoritative": True}


@app.get("/api/rooms/{code}/session/{pid}")
async def session_status(code: str, pid: str) -> dict[str, Any]:
    room = await get_room(code)
    if pid not in room.players:
        raise HTTPException(status_code=404, detail="Player not found")
    return {"valid": True, "phase": room.state.phase if room.state else "lobby"}


@app.post("/api/rooms")
async def create_room(payload: NameRequest) -> dict[str, str]:
    name = clean_name(payload.name)
    if not name:
        raise HTTPException(status_code=422, detail="Name cannot be blank")
    async with rooms_lock:
        now = time.monotonic()
        for code, room in list(rooms.items()):
            if not room.sockets and now - room.last_activity > ROOM_TTL:
                rooms.pop(code, None)
        code = new_code()
        while code in rooms:
            code = new_code()
        pid = new_id()
        rooms[code] = Room(code=code, players={pid: {"id": pid, "username": name}})
    return {"room": code, "player_id": pid}


@app.post("/api/rooms/{code}/join")
async def join_room(code: str, payload: NameRequest) -> dict[str, str]:
    room = await get_room(code)
    name = clean_name(payload.name)
    if not name:
        raise HTTPException(status_code=422, detail="Name cannot be blank")
    async with room.lock:
        if room.state is not None:
            raise HTTPException(status_code=409, detail="That game has already started")
        if len(room.players) >= 5:
            raise HTTPException(status_code=409, detail="Table is full (5 players maximum)")
        if any(x["username"].casefold() == name.casefold() for x in room.players.values()):
            raise HTTPException(status_code=409, detail="That name is already taken in this room")
        pid = new_id()
        room.players[pid] = {"id": pid, "username": name}
        room.last_activity = time.monotonic()
    return {"room": room.code, "player_id": pid}


@app.post("/api/rooms/{code}/leave")
async def leave_room(code: str, payload: LeaveRequest) -> dict[str, bool]:
    room = await get_room(code)
    async with room.lock:
        if payload.player_id not in room.players:
            raise HTTPException(status_code=404, detail="Player not found")
        if room.state is not None:
            return {"removed": False}
        room.players.pop(payload.player_id)
        room.sockets.pop(payload.player_id, None)
        room.last_activity = time.monotonic()
        if room.players:
            await broadcast(room)
    if not room.players:
        async with rooms_lock:
            rooms.pop(room.code, None)
    return {"removed": True}


async def handle(room: Room, pid: str, data: Any) -> str | None:
    if not isinstance(data, dict):
        return "Action must be an object"
    if room.state is None:
        action = data.get("type") or data.get("action")
        if action not in {"start", "START_GAME"}:
            return "Waiting for the host to start"
        if pid != next(iter(room.players), None):
            return "Only the host can start"
        if len(room.players) < 2:
            return "Invite at least one more player"
        try:
            room.state = room.engine.new_game(list(room.players.values()))
            for player in room.state.player_list:
                player.connected = player.id in room.sockets
        except RuleError as exc:
            return str(exc)
        return None
    try:
        room.engine.apply(room.state, pid, data)
        return None
    except (RuleError, ValueError, KeyError, TypeError) as exc:
        return str(exc)


@app.websocket("/ws/{code}/{pid}")
async def websocket_endpoint(websocket: WebSocket, code: str, pid: str) -> None:
    room = rooms.get(code.upper().strip())
    if room is None or pid not in room.players:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    previous: WebSocket | None = None
    async with room.lock:
        previous = room.sockets.get(pid)
        room.sockets[pid] = websocket
        room.last_activity = time.monotonic()
        if room.state and pid in room.state.players:
            room.state.players[pid].connected = True
        await broadcast(room)
    if previous and previous is not websocket:
        asyncio.create_task(close_old(previous))
    try:
        while True:
            data = await websocket.receive_json()
            async with room.lock:
                if room.sockets.get(pid) is not websocket:
                    await websocket.close(code=4001, reason="Reconnected elsewhere")
                    return
                room.last_activity = time.monotonic()
                error = await handle(room, pid, data)
                if error:
                    await websocket.send_json({"type": "error", "message": error})
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
