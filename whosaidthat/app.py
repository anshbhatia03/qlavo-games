from __future__ import annotations

import asyncio
import json
import random
import re
import secrets
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
QUOTES_PATH = BASE / "quotes.json"
app = FastAPI(title="Who Said That?")

DISPLAY_ORDER = ["Ansh", "Neel", "Vikram", "Uttkarsh", "Ravtej", "Aryeman", "Pavit", "Gaurav", "Dhruv", "Yash", "Sahil", "Sid"]
COLORS = {
    "Ansh": "#ff6b6b", "Neel": "#4ecdc4", "Vikram": "#ffd23f", "Uttkarsh": "#a78bfa",
    "Ravtej": "#f97316", "Aryeman": "#34d399", "Pavit": "#60a5fa", "Gaurav": "#f472b6",
    "Dhruv": "#94a3b8", "Yash": "#facc15", "Sahil": "#38bdf8", "Sid": "#fb7185",
}


def load_quotes() -> list[dict[str, Any]]:
    payload = json.loads(QUOTES_PATH.read_text(encoding="utf-8"))
    quotes = payload.get("quotes", [])
    required = {"id", "text", "sender", "timestamp", "sourceIndices"}
    clean: list[dict[str, Any]] = []
    seen: set[str] = set()
    for quote in quotes:
        if not required.issubset(quote) or quote["id"] in seen:
            continue
        seen.add(quote["id"])
        clean.append(quote)
    return clean


ALL_QUOTES = load_quotes()
PRESENT_SENDERS = {q["sender"] for q in ALL_QUOTES}
ANSWER_OPTIONS = [name for name in DISPLAY_ORDER if name in PRESENT_SENDERS]
ANSWER_OPTIONS += sorted(PRESENT_SENDERS - set(ANSWER_OPTIONS))
SENDER_META = {name: {"color": COLORS.get(name, "#64748b"), "initial": name[:2] if name == "Aryeman" else name[:1]} for name in ANSWER_OPTIONS}
CONTEXT_ALIASES = {
    "Ansh": ("Ansh",),
    "Neel": ("Neel",),
    "Vikram": ("Vikram", "Vikram 2"),
    "Uttkarsh": ("Uttkarsh", "Yutt"),
    "Ravtej": ("Ravtej", "R'tej"),
    "Aryeman": ("Aryeman",),
    "Pavit": ("Pavit",),
    "Gaurav": ("Gaurav", "G aurav"),
}


def new_id(prefix: str = "p") -> str:
    return prefix + secrets.token_urlsafe(8).replace("-", "").replace("_", "")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def new_code() -> str:
    return "".join(random.choice(string.ascii_uppercase) for _ in range(4))


def clean_name(name: str) -> str:
    return " ".join(name.strip().split())[:18]


def anonymous_context(messages: list[dict[str, Any]], hidden_sender: str) -> list[dict[str, str]]:
    aliases = CONTEXT_ALIASES.get(hidden_sender, (hidden_sender,))
    pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(alias) for alias in sorted(aliases, key=len, reverse=True)) + r")(?!\w)",
        re.IGNORECASE,
    )
    return [{"text": pattern.sub("[name]", str(message.get("text", "")))} for message in messages[:2]]


@dataclass
class Player:
    id: str
    token: str
    name: str
    host: bool = False
    connected: bool = False
    ws: WebSocket | None = None
    score: int = 0
    streak: int = 0


@dataclass
class RoundState:
    quote: dict[str, Any]
    eligible_voters: set[str] = field(default_factory=set)
    votes: dict[str, str] = field(default_factory=dict)
    revealed: bool = False
    reactions: dict[str, set[str]] = field(default_factory=lambda: {"😂": set(), "💀": set(), "😭": set(), "🧢": set()})
    favorites: set[str] = field(default_factory=set)


@dataclass
class Room:
    code: str
    host_id: str
    players: dict[str, Player] = field(default_factory=dict)
    phase: str = "lobby"  # lobby | voting | reveal | finished
    round_number: int = 0
    deck: list[dict[str, Any]] = field(default_factory=list)
    used_ids: set[str] = field(default_factory=set)
    current_round: RoundState | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    hall_of_fame: dict[str, dict[str, Any]] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def player_list(self) -> list[Player]:
        return list(self.players.values())

    @property
    def connected_players(self) -> list[Player]:
        return [p for p in self.player_list if p.connected]

    def reset_deck(self) -> None:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for quote in ALL_QUOTES:
            buckets.setdefault(quote["sender"], []).append(quote.copy())
        for bucket in buckets.values():
            random.shuffle(bucket)
        play_order: list[dict[str, Any]] = []
        while buckets:
            sender = random.choice(tuple(buckets))
            play_order.append(buckets[sender].pop())
            if not buckets[sender]:
                del buckets[sender]
        self.deck = list(reversed(play_order))
        self.used_ids.clear()

    def next_quote(self) -> dict[str, Any] | None:
        if not self.deck and ALL_QUOTES:
            self.reset_deck()
        while self.deck:
            quote = self.deck.pop()
            if quote["id"] not in self.used_ids:
                self.used_ids.add(quote["id"])
                return quote
        return None

    def required_voters(self) -> set[str]:
        connected = {p.id for p in self.connected_players}
        if self.current_round:
            return self.current_round.eligible_voters & connected
        return connected

    def public_hall_of_fame(self) -> list[dict[str, Any]]:
        return sorted(self.hall_of_fame.values(), key=lambda x: (-x["favorites"], x["round"]))[:5]

    def state_for(self, viewer_id: str) -> dict[str, Any]:
        current = None
        my_vote = None
        public_votes: dict[str, str] = {}
        reactions = {emoji: 0 for emoji in ("😂", "💀", "😭", "🧢")}
        favorite_count = 0
        has_favorited = False

        if self.current_round:
            round_state = self.current_round
            quote = round_state.quote
            my_vote = round_state.votes.get(viewer_id)
            context_before = anonymous_context(quote.get("contextBefore", []), quote["sender"])
            context_after = anonymous_context(quote.get("contextAfter", []), quote["sender"])
            if round_state.revealed:
                current = {
                    "id": quote["id"],
                    "text": quote["text"],
                    "sender": quote["sender"],
                    "timestamp": quote.get("timestamp", ""),
                    "contextBefore": context_before,
                    "contextAfter": context_after,
                    "isSequence": quote.get("isSequence", False),
                }
                public_votes = dict(round_state.votes)
            else:
                current = {
                    "id": quote["id"],
                    "text": quote["text"],
                    "contextBefore": context_before,
                    "contextAfter": context_after,
                    "isSequence": quote.get("isSequence", False),
                }
            reactions = {emoji: len(voters) for emoji, voters in round_state.reactions.items()}
            favorite_count = len(round_state.favorites)
            has_favorited = viewer_id in round_state.favorites

        return {
            "type": "state",
            "room": self.code,
            "viewer": viewer_id,
            "phase": self.phase,
            "is_host": viewer_id == self.host_id,
            "round_number": self.round_number,
            "quotes_total": len(ALL_QUOTES),
            "answer_options": ANSWER_OPTIONS,
            "sender_meta": SENDER_META,
            "players": [
                {
                    "id": player.id,
                    "name": player.name,
                    "host": player.id == self.host_id,
                    "connected": player.connected,
                    "score": player.score,
                    "streak": player.streak,
                }
                for player in self.player_list
            ],
            "current": current,
            "my_vote": my_vote,
            "votes": public_votes,
            "voted_count": len(self.current_round.votes) if self.current_round else 0,
            "required_voters": len(self.required_voters()) if self.current_round else 0,
            "reactions": reactions,
            "favorite_count": favorite_count,
            "has_favorited": has_favorited,
            "history": self.history[-8:],
            "hall_of_fame": self.public_hall_of_fame(),
        }


rooms: dict[str, Room] = {}
rooms_lock = asyncio.Lock()


class NameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=18)


class CreateResponse(BaseModel):
    room: str
    player_id: str
    token: str


async def get_room(code: str) -> Room:
    room = rooms.get(code.upper())
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@app.get("/", response_class=FileResponse)
async def index() -> FileResponse:
    return FileResponse(BASE / "index.html")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "whosaidthat", "quotes": len(ALL_QUOTES), "options": len(ANSWER_OPTIONS)}


@app.get("/api/meta")
async def meta() -> dict[str, Any]:
    return {"quotes": len(ALL_QUOTES), "answer_options": ANSWER_OPTIONS, "sender_meta": SENDER_META}


@app.post("/api/rooms", response_model=CreateResponse)
async def create_room(payload: NameRequest) -> CreateResponse:
    name = clean_name(payload.name)
    if not name:
        raise HTTPException(status_code=400, detail="Enter a name")
    async with rooms_lock:
        code = new_code()
        while code in rooms:
            code = new_code()
        player_id = new_id()
        room = Room(code=code, host_id=player_id)
        room.reset_deck()
        token = new_token()
        room.players[player_id] = Player(id=player_id, token=token, name=name, host=True)
        rooms[code] = room
    return CreateResponse(room=code, player_id=player_id, token=token)


@app.post("/api/rooms/{code}/join", response_model=CreateResponse)
async def join_room(code: str, payload: NameRequest) -> CreateResponse:
    room = await get_room(code.strip().upper())
    name = clean_name(payload.name)
    if not name:
        raise HTTPException(status_code=400, detail="Enter a name")
    async with room.lock:
        if room.phase != "lobby":
            raise HTTPException(status_code=409, detail="That room has already started")
        if len(room.players) >= 12:
            raise HTTPException(status_code=409, detail="Room is full")
        if any(player.name.casefold() == name.casefold() for player in room.player_list):
            raise HTTPException(status_code=409, detail="That name is already in the room")
        player_id = new_id()
        token = new_token()
        room.players[player_id] = Player(id=player_id, token=token, name=name)
    return CreateResponse(room=room.code, player_id=player_id, token=token)


async def broadcast(room: Room) -> None:
    dead: list[tuple[str, WebSocket]] = []
    for player_id, player in list(room.players.items()):
        ws = player.ws
        if not ws:
            continue
        try:
            await ws.send_json(room.state_for(player_id))
        except Exception:
            dead.append((player_id, ws))
    for player_id, failed_ws in dead:
        player = room.players[player_id]
        if player.ws is failed_ws:
            player.connected = False
            player.ws = None


def start_next_round(room: Room) -> str | None:
    quote = room.next_quote()
    if not quote:
        room.phase = "finished"
        room.current_round = None
        return "That was the full quote pool"
    room.round_number += 1
    room.current_round = RoundState(quote=quote, eligible_voters={p.id for p in room.connected_players})
    room.phase = "voting"
    return None


def reveal_round(room: Room) -> None:
    if not room.current_round or room.current_round.revealed:
        return
    current = room.current_round
    current.revealed = True
    room.phase = "reveal"
    sender = current.quote["sender"]
    correct_names: list[str] = []
    for player_id in current.eligible_voters:
        player = room.players.get(player_id)
        if not player:
            continue
        guess = current.votes.get(player_id)
        if guess == sender:
            player.score += 2
            player.streak += 1
            if player.streak and player.streak % 3 == 0:
                player.score += 1
            correct_names.append(player.name)
        else:
            player.streak = 0
    room.history.append({
        "round": room.round_number,
        "text": current.quote["text"][:100],
        "sender": sender,
        "correct": len(correct_names),
        "total": len(current.eligible_voters),
        "correct_names": correct_names,
    })


def everyone_connected_has_voted(room: Room) -> bool:
    if not room.current_round:
        return False
    required = room.required_voters()
    return bool(required) and required.issubset(room.current_round.votes)


async def handle_action(room: Room, player_id: str, action: dict[str, Any]) -> str | None:
    player = room.players.get(player_id)
    if not player:
        return "Player not found"
    kind = action.get("action")

    if kind == "start_game":
        if player_id != room.host_id:
            return "Only the host can start"
        if room.phase != "lobby":
            return "The game has already started"
        if len(room.connected_players) < 2:
            return "At least two connected players are needed"
        room.round_number = 0
        room.history.clear()
        room.hall_of_fame.clear()
        room.reset_deck()
        for participant in room.player_list:
            participant.score = 0
            participant.streak = 0
        return start_next_round(room)

    if kind == "vote":
        if room.phase != "voting" or not room.current_round:
            return "Voting is closed"
        guess = action.get("guess")
        if guess not in ANSWER_OPTIONS:
            return "Invalid answer"
        if player_id in room.current_round.votes:
            return "Your vote is already locked"
        room.current_round.votes[player_id] = guess
        if everyone_connected_has_voted(room):
            reveal_round(room)
        return None

    if kind == "reveal":
        if player_id != room.host_id:
            return "Only the host can reveal"
        if room.phase != "voting" or not room.current_round:
            return "Nothing to reveal"
        if not room.current_round.votes:
            return "Wait for at least one vote"
        reveal_round(room)
        return None

    if kind == "next_round":
        if player_id != room.host_id:
            return "Only the host can continue"
        if room.phase != "reveal":
            return "Reveal the answer first"
        return start_next_round(room)

    if kind == "end_game":
        if player_id != room.host_id:
            return "Only the host can end the game"
        if room.phase not in ("voting", "reveal"):
            return "The game is not running"
        room.phase = "finished"
        return None

    if kind == "react":
        if room.phase != "reveal" or not room.current_round:
            return "Reactions open after the reveal"
        emoji = action.get("emoji")
        if emoji not in room.current_round.reactions:
            return "Invalid reaction"
        voters = room.current_round.reactions[emoji]
        if player_id in voters:
            voters.remove(player_id)
        else:
            voters.add(player_id)
        return None

    if kind == "favorite":
        if room.phase != "reveal" or not room.current_round:
            return "Favorites open after the reveal"
        favorites = room.current_round.favorites
        if player_id in favorites:
            favorites.remove(player_id)
        else:
            favorites.add(player_id)
        quote = room.current_round.quote
        if favorites:
            room.hall_of_fame[quote["id"]] = {
                "id": quote["id"], "text": quote["text"][:140], "sender": quote["sender"],
                "favorites": len(favorites), "round": room.round_number,
            }
        else:
            room.hall_of_fame.pop(quote["id"], None)
        return None

    if kind == "restart":
        if player_id != room.host_id:
            return "Only the host can restart"
        room.phase = "lobby"
        room.round_number = 0
        room.current_round = None
        room.history.clear()
        room.hall_of_fame.clear()
        room.reset_deck()
        for participant in room.player_list:
            participant.score = 0
            participant.streak = 0
        return None

    return "Unknown action"


@app.websocket("/ws/{code}")
async def websocket_endpoint(websocket: WebSocket, code: str) -> None:
    room = rooms.get(code.upper())
    await websocket.accept()
    if not room:
        await websocket.close(code=4404)
        return
    try:
        auth = await asyncio.wait_for(websocket.receive_json(), timeout=5)
    except Exception:
        await websocket.close(code=4401)
        return
    token = auth.get("token", "") if auth.get("action") == "authenticate" else ""
    player = next((candidate for candidate in room.player_list if secrets.compare_digest(candidate.token, token)), None)
    if not player:
        await websocket.close(code=4404)
        return
    player_id = player.id
    previous = player.ws
    player.ws = websocket
    player.connected = True
    if previous and previous is not websocket:
        try:
            await previous.close(code=4001, reason="Session opened elsewhere")
        except Exception:
            pass
    await broadcast(room)
    try:
        while True:
            payload = await websocket.receive_json()
            async with room.lock:
                error = await handle_action(room, player_id, payload)
                if error:
                    await websocket.send_json({"type": "error", "message": error})
                await broadcast(room)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if player.ws is websocket:
            player.ws = None
            player.connected = False
        async with room.lock:
            if player_id == room.host_id:
                replacement = next((p for p in room.connected_players if p.id != player_id), None)
                if replacement:
                    room.host_id = replacement.id
            if room.phase == "voting" and everyone_connected_has_voted(room):
                reveal_round(room)
            await broadcast(room)
