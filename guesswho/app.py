from __future__ import annotations

import asyncio
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
app = FastAPI(title="Guess Who: The Circle")

CANDIDATES = [
    "Yash", "Inan", "Sid", "Karan", "Chaitanya", "Vikram", "Ansh", "Aditya Swarup",
    "Deepankar", "Satvik", "Navya", "Vanya", "Raseel", "Adhyan", "Juhi", "Jaishree",
    "Dhruv Khanna", "Nysa", "Neel", "Uttkarsh", "Chopra", "Tia", "Ketch", "Ravtej",
]


def new_id(prefix: str = "p") -> str:
    return prefix + secrets.token_urlsafe(8).replace("-", "").replace("_", "")


def new_code() -> str:
    return "".join(random.choice(string.ascii_uppercase) for _ in range(4))


@dataclass
class Player:
    id: str
    name: str
    host: bool = False
    connected: bool = False
    ws: WebSocket | None = None
    secret: str | None = None
    active: bool = True
    wins: int = 0


@dataclass
class Room:
    code: str
    host_id: str
    players: dict[str, Player] = field(default_factory=dict)
    phase: str = "lobby"
    round_number: int = 0
    current_id: str | None = None
    target_id: str | None = None
    last_guess: dict[str, Any] | None = None
    winner_id: str | None = None
    event_message: str = "Waiting for the host to start the room."
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def player_list(self) -> list[Player]:
        return list(self.players.values())

    @property
    def active_players(self) -> list[Player]:
        return [p for p in self.player_list if p.active]

    def next_active_after(self, player_id: str) -> Player | None:
        active = self.active_players
        if len(active) <= 1:
            return active[0] if active else None
        ids = [p.id for p in self.player_list]
        start = ids.index(player_id)
        for offset in range(1, len(ids) + 1):
            candidate = self.players[ids[(start + offset) % len(ids)]]
            if candidate.active:
                return candidate
        return None

    def set_turn(self, current: Player) -> None:
        self.current_id = current.id
        target = self.next_active_after(current.id)
        self.target_id = target.id if target else None
        self.phase = "playing"

    def state_for(self, viewer_id: str) -> dict[str, Any]:
        viewer = self.players.get(viewer_id)
        current = self.players.get(self.current_id) if self.current_id else None
        target = self.players.get(self.target_id) if self.target_id else None
        return {
            "type": "state",
            "room": self.code,
            "viewer": viewer_id,
            "phase": self.phase,
            "round_number": self.round_number,
            "candidate_names": CANDIDATES,
            "your_secret": viewer.secret if viewer and self.phase != "lobby" else None,
            "current_id": self.current_id,
            "current_name": current.name if current else None,
            "target_id": self.target_id,
            "target_name": target.name if target else None,
            "last_guess": self.last_guess or {},
            "winner_id": self.winner_id,
            "event_message": self.event_message,
            "is_host": viewer_id == self.host_id,
            "my_turn": self.phase == "playing" and viewer_id == self.current_id,
            "players": [
                {
                    "id": p.id,
                    "name": p.name,
                    "host": p.host,
                    "connected": p.connected,
                    "active": p.active,
                    "wins": p.wins,
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


def clean_name(name: str) -> str:
    return " ".join(name.strip().split())[:18]


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
    return {"status": "ok", "service": "guesswho", "candidates": str(len(CANDIDATES)), "mode": "call-only"}


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
            raise HTTPException(status_code=409, detail="That room has already started")
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


def start_round(room: Room) -> None:
    room.round_number += 1
    room.phase = "playing"
    room.winner_id = None
    room.last_guess = None
    for player, secret in zip(room.player_list, random.sample(CANDIDATES, len(room.player_list))):
        player.secret = secret
        player.active = True
    first = room.player_list[0]
    room.set_turn(first)
    target = room.players[room.target_id]
    room.event_message = f"Round {room.round_number}: {first.name} asks {target.name} on the call."


def finish_if_one_left(room: Room) -> bool:
    active = room.active_players
    if len(active) != 1:
        return False
    room.winner_id = active[0].id
    room.players[room.winner_id].wins += 1
    room.phase = "results"
    room.event_message = f"{active[0].name} is the last one standing and wins Round {room.round_number}."
    return True


def advance_after_current(room: Room, old_current: str) -> None:
    next_player = room.next_active_after(old_current)
    if next_player is None or finish_if_one_left(room):
        return
    room.set_turn(next_player)
    target = room.players[room.target_id]
    room.event_message = f"{next_player.name}'s turn. Ask {target.name} on the call."


async def handle_action(room: Room, pid: str, action: dict[str, Any]) -> str | None:
    player = room.players.get(pid)
    if not player:
        return "Player not found"
    kind = action.get("action")

    if kind == "start":
        if pid != room.host_id:
            return "Only the host can start"
        if room.phase != "lobby":
            return "The room has already started"
        if len(room.players) < 2:
            return "Invite at least one friend first"
        start_round(room)
        return None

    if kind == "pass_turn":
        if room.phase != "playing" or pid != room.current_id:
            return "It is not your turn"
        old = room.current_id
        advance_after_current(room, old)
        return None

    if kind == "guess":
        if room.phase != "playing":
            return "The round is not active"
        if pid != room.current_id and not player.active:
            return "You are out of this round"
        candidate = str(action.get("candidate", "")).strip()
        if candidate not in CANDIDATES:
            return "Choose a face from the board"
        target = room.players[room.target_id]
        correct = candidate == target.secret
        room.last_guess = {
            "guesser_id": pid,
            "guesser_name": player.name,
            "candidate": candidate,
            "correct": correct,
        }
        if correct:
            room.winner_id = pid
            player.wins += 1
            room.phase = "results"
            room.event_message = f"{player.name} guessed {target.secret} and wins Round {room.round_number}."
            return None
        # wrong guess: just a lost turn
        old = room.current_id
        advance_after_current(room, old)
        return None

    if kind == "next_round":
        if pid != room.host_id:
            return "Only the host can start the next round"
        if room.phase != "results":
            return "Finish this round first"
        start_round(room)
        return None

    if kind == "reset":
        if pid != room.host_id:
            return "Only the host can reset the room"
        room.phase = "lobby"
        room.round_number = 0
        room.current_id = None
        room.target_id = None
        room.last_guess = None
        room.winner_id = None
        room.event_message = "Waiting for the host to start the room."
        for p in room.player_list:
            p.secret = None
            p.active = True
            p.wins = 0
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
            action = await websocket.receive_json()
            async with room.lock:
                error = await handle_action(room, pid, action)
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
