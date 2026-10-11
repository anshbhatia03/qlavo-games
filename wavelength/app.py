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
app = FastAPI(title="Wavelength")

WIN_SCORE = 10  # first to 10 ends the match; most points wins

# Universal spectrum categories: [left pole, right pole]
CATEGORIES: list[list[str]] = [
    ['Bad loser', 'Good loser'],
    ['Not jealous', 'Extremely jealous'],
    ['Not flirty', 'Extremely flirty'],
    ['Very innocent', 'Very dirty-minded'],
    ['Terrible texter', 'Amazing texter'],
    ['Very shy', 'Very confident'],
    ['Very loyal', 'Very disloyal'],
    ['Very trusting', 'Very suspicious'],
    ['Very private', 'Overshares everything'],
    ['Very calm', 'Very dramatic'],
    ['Very chill', 'Very intense'],
    ['Very forgiving', 'Holds grudges forever'],
    ['Very honest', 'Lies constantly'],
    ['Very humble', 'Massive ego'],
    ['Very mature', 'Very immature'],
    ['Very responsible', 'Completely reckless'],
    ['Very patient', 'Zero patience'],
    ['Very organised', 'Total mess'],
    ['Very punctual', 'Always late'],
    ['Very generous', 'Very stingy'],
    ['Very reliable', 'Completely unreliable'],
    ['Very polite', 'Extremely rude'],
    ['Very friendly', 'Very unfriendly'],
    ['Very social', 'Very antisocial'],
    ['Very quiet', 'Very loud'],
    ['Very awkward', 'Very smooth'],
    ['Very boring', 'Very entertaining'],
    ['Very serious', 'Never serious'],
    ['Very sensible', 'Very stupid'],
    ['Very cautious', 'Very impulsive'],
    ['Very lazy', 'Very hardworking'],
    ['Very ambitious', 'No ambition'],
    ['Very cheap', 'Spends recklessly'],
    ['Very broke', 'Very rich'],
    ['Terrible taste', 'Amazing taste'],
    ['Very uncool', 'Extremely cool'],
    ['Very cringe', 'Very smooth'],
    ['Very unattractive', 'Extremely attractive'],
    ['Not sexy', 'Extremely sexy'],
    ['Not romantic', 'Extremely romantic'],
    ['Not dateable', 'Extremely dateable'],
    ['Terrible partner', 'Perfect partner'],
    ['Terrible first date', 'Perfect first date'],
    ['No chemistry', 'Insane chemistry'],
    ['Completely platonic', 'Obviously into each other'],
    ['Not interested', 'Obsessed'],
    ['Barely flirting', 'Extremely obvious flirting'],
    ['Harmless message', 'Extremely risky message'],
    ['Totally appropriate', 'Wildly inappropriate'],
    ['Completely faithful', 'Basically cheating'],
    ['Tiny lie', 'Massive betrayal'],
    ['Small red flag', 'Huge red flag'],
    ['Terrible kisser', 'Amazing kisser'],
    ['Vanilla', 'Very kinky'],
    ['Completely sober', 'Absolutely wasted'],
    ['Good drunk', 'Nightmare drunk'],
    ['Safe decision', 'Terrible decision'],
    ['Very legal', 'Definitely illegal'],
    ['Morally fine', 'Completely evil'],
    ['Mild prank', 'Friendship-ending prank'],
    ['Tiny secret', 'Life-changing secret'],
    ['Harmless gossip', 'Nuclear gossip'],
    ['Easy to forgive', 'Impossible to forgive'],
    ['Barely embarrassing', 'Mortifying'],
    ['Not awkward', 'Unbearably awkward'],
    ['Not funny', 'Hilarious'],
    ['Mild roast', 'Absolutely brutal roast'],
    ['Harmless banter', 'Way too personal'],
    ['No drama', 'Maximum drama'],
    ['Normal behaviour', 'Completely unhinged'],
    ['Very sane', 'Absolutely insane'],
    ['Very predictable', 'Completely unpredictable'],
    ['Very trustworthy', 'Cannot trust at all'],
    ['Very innocent-looking', 'Looks guilty as hell'],
    ['Unlikely to get arrested', 'Definitely getting arrested'],
    ['Would survive easily', 'Dies immediately'],
    ['Terrible wingman', 'Perfect wingman'],
    ['Terrible roommate', 'Perfect roommate'],
    ['Terrible travel partner', 'Perfect travel partner'],
    ['Worst person to lend money to', 'Safest person to lend money to'],
    ['Worst person to tell a secret', 'Best person to tell a secret'],
    ['Cheap', 'Expensive'],
    ['Healthy', 'Unhealthy'],
    ['Safe', 'Dangerous'],
    ['Easy', 'Difficult'],
    ['Boring', 'Exciting'],
    ['Useless', 'Extremely useful'],
    ['Common', 'Rare'],
    ['Ugly', 'Beautiful'],
    ['Bad smell', 'Amazing smell'],
    ['Bad food', 'Amazing food'],
    ['Terrible purchase', 'Amazing purchase'],
    ['Not worth the money', 'Absolutely worth it'],
    ['Bad holiday', 'Dream holiday'],
    ['Terrible job', 'Dream job'],
    ['Bad place for a date', 'Perfect place for a date'],
    ['Bad gift', 'Perfect gift'],
    ['Bad drunk food', 'Perfect drunk food'],
    ['Bad thing to text an ex', 'Great thing to text an ex'],
    ['Safe thing to say on a first date', 'Insane thing to say on a first date'],
    ['Bad excuse for being late', 'Perfect excuse'],
    ['Bad reason to skip work', 'Completely valid reason'],
    ['Bad reason to break up', 'Completely valid reason'],
    ['Bad person to date', 'Perfect person to date'],
    ['Bad celebrity crush', 'Perfect celebrity crush'],
]


def new_id(prefix: str = "p") -> str:
    return prefix + secrets.token_urlsafe(8).replace("-", "").replace("_", "")


def new_code() -> str:
    return "".join(random.choice(string.ascii_uppercase) for _ in range(4))


def points_for_distance(dist: float) -> int:
    """Demo-exact tiers, matching the drawn bands: within 2.5 -> 4 pts,
    within 5.5 -> 3 pts, within 9 -> 2 pts, otherwise 0 (miss)."""
    if dist <= 2.5:
        return 4
    if dist <= 5.5:
        return 3
    if dist <= 9:
        return 2
    return 0


BOT_NAMES = ["Riya", "Dev", "Sam", "Ira", "Kabir", "Zoya"]
BOT_SKILLS = [6, 14, 28]  # gaussian stdev per bot personality: sharp, decent, wild


@dataclass
class Player:
    id: str
    name: str
    ws: WebSocket | None = None
    connected: bool = False
    is_bot: bool = False


@dataclass
class Room:
    code: str
    host_id: str
    players: dict[str, Player] = field(default_factory=dict)
    phase: str = "lobby"  # lobby | psychic | guessing | reveal | match_over
    round_number: int = 0
    psychic_idx: int = 0
    deck: list[list[str]] = field(default_factory=list)
    left: str = ""
    right: str = ""
    target: int = 0
    psychic_id: str | None = None
    guesses: dict[str, float] = field(default_factory=dict)
    locked: set[str] = field(default_factory=set)
    scores: dict[str, int] = field(default_factory=dict)
    last_reveal: dict[str, Any] | None = None
    bot_scheduled: dict[str, str] = field(default_factory=dict)
    event_message: str = "Waiting for the host to start the match."
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def player_list(self) -> list[Player]:
        return list(self.players.values())

    def current_psychic(self) -> Player | None:
        if not self.player_list:
            return None
        ordered = self.player_list
        idx = self.psychic_idx % len(ordered)
        return ordered[idx]

    def guessers(self) -> list[Player]:
        psy = self.current_psychic()
        return [p for p in self.player_list if p is not psy]


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
    return {
        "status": "ok",
        "service": "wavelength",
        "mode": "individual",
        "categories": str(len(CATEGORIES)),
        "win_score": "unlimited",
        "tiers": "4/3/2/0",
    }


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
        room.players[pid] = Player(id=pid, name=name)
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
            await player.ws.send_json(state_for(room, pid))
        except Exception:
            dead.append(pid)
    for pid in dead:
        room.players[pid].connected = False
        room.players[pid].ws = None


def start_round(room: Room) -> None:
    if not room.deck:
        room.deck = random.sample(CATEGORIES, len(CATEGORIES))
    pair = room.deck.pop()
    room.left, room.right = pair
    # keep the full scoring wedge (pink ±9) inside the arc
    room.target = random.randint(10, 90)
    room.guesses = {}
    room.locked = set()
    room.last_reveal = None
    room.bot_scheduled = {}
    room.round_number += 1
    psychic = room.current_psychic()
    room.psychic_id = psychic.id if psychic else None
    room.phase = "psychic"
    if psychic:
        room.event_message = f"Round {room.round_number}: {psychic.name} spins first."
    else:
        room.event_message = f"Round {room.round_number}: waiting for players."


def resolve_round(room: Room) -> None:
    results = []
    for pid, val in room.guesses.items():
        if pid not in room.players:
            continue
        dist = abs(val - room.target)
        pts = points_for_distance(dist)
        room.scores[pid] = room.scores.get(pid, 0) + pts
        results.append({
            "id": pid,
            "name": room.players[pid].name,
            "value": val,
            "distance": dist,
            "points": pts,
        })
    results.sort(key=lambda r: (-r["points"], r["distance"]))
    room.last_reveal = {
        "round": room.round_number,
        "left": room.left,
        "right": room.right,
        "target": room.target,
        "results": results,
        "scores": dict(room.scores),
    }
    ranked = sorted(room.scores.items(), key=lambda kv: kv[1], reverse=True)
    top = ranked[0][1] if ranked else 0
    leaders = [pid for pid, sc in ranked if sc == top]
    if len(leaders) == 1 and top > 0:
        room.phase = "reveal"
        room.event_message = f"{room.players[leaders[0]].name} leads with {top}. No target — play forever."
    else:
        room.phase = "reveal"
        best = results[0]["name"] if results else "Nobody"
        best_pts = results[0]["points"] if results else 0
        room.event_message = f"Closest: {best} (+{best_pts})."


def state_for(room: Room, viewer_id: str) -> dict[str, Any]:
    viewer = room.players.get(viewer_id)
    psychic = room.players.get(room.psychic_id) if room.psychic_id else None
    is_psychic = bool(viewer and psychic and viewer.id == psychic.id)
    revealed = room.phase in ("reveal", "match_over")
    leaderboard = [
        {"id": p.id, "name": p.name, "score": room.scores.get(p.id, 0)}
        for p in room.player_list
    ]
    leaderboard.sort(key=lambda e: -e["score"])
    winner = None
    if room.phase == "match_over":
        ranked = sorted(room.scores.items(), key=lambda kv: kv[1], reverse=True)
        winner = ranked[0][0] if ranked else None
    else:
        ranked = sorted(room.scores.items(), key=lambda kv: kv[1], reverse=True)
        winner = ranked[0][0] if ranked else None
    return {
        "type": "state",
        "room": room.code,
        "viewer": viewer_id,
        "phase": room.phase,
        "round_number": room.round_number,
        "is_host": viewer_id == room.host_id,
        "win_score": WIN_SCORE,
        # secrecy: target visible ONLY to the psychic until the reveal
        "target": room.target if (is_psychic or revealed) else None,
        "show_bands": is_psychic or revealed,
        "left": room.left or None,
        "right": room.right or None,
        "is_psychic": is_psychic,
        "psychic_id": room.psychic_id,
        "psychic_name": psychic.name if psychic else None,
        "my_guess": room.guesses.get(viewer_id),
        "i_locked": viewer_id in room.locked if viewer else False,
        "locked_count": len(room.locked),
        "guesser_count": len(room.guessers()) if room.phase in ("psychic", "guessing") else 0,
        "leaderboard": leaderboard,
        "scores": dict(room.scores),
        "last_reveal": room.last_reveal,
        "winner": winner,
        "winner_name": room.players[winner].name if winner else None,
        "event_message": room.event_message,
        "players": [
            {
                "id": p.id,
                "name": p.name,
                "connected": p.connected,
                "is_host": p.id == room.host_id,
                "is_bot": p.is_bot,
                "is_psychic": p.id == room.psychic_id and room.phase not in ("lobby", "match_over"),
            }
            for p in room.player_list
        ],
    }


def bot_skill(room: Room, pid: str) -> float:
    idx = list(room.players).index(pid) if pid in room.players else 0
    return BOT_SKILLS[idx % len(BOT_SKILLS)]


def schedule_bots(room: Room) -> None:
    """Queue pending bot moves for the current phase (one task per bot per phase)."""
    key = f"{room.phase}:{room.round_number}"
    for p in room.player_list:
        if not p.is_bot:
            continue
        if room.phase == "guessing" and p.id == room.psychic_id:
            continue
        if room.phase not in ("psychic", "guessing"):
            continue
        if room.bot_scheduled.get(p.id) == key:
            continue
        room.bot_scheduled[p.id] = key
        asyncio.get_running_loop().create_task(run_bot_move(room, p.id, key))


async def run_bot_move(room: Room, pid: str, key: str) -> None:
    try:
        await asyncio.sleep(random.uniform(1.2, 3.0))
        async with room.lock:
            # stale check: round moved on without this bot acting
            cur = f"{room.phase}:{room.round_number}"
            if cur != key and not (key.startswith("psychic:") and cur.startswith("guessing:") and key.split(":")[1] == cur.split(":")[1]):
                room.bot_scheduled.pop(pid, None)
                return
            player = room.players.get(pid)
            if not player or not player.is_bot:
                return
            acted = False
            if room.phase == "psychic" and pid == room.psychic_id:
                room.phase = "guessing"
                room.event_message = "Clue time — everyone else, set your dial."
                acted = True
            elif room.phase == "guessing" and pid != room.psychic_id and pid not in room.locked:
                sigma = bot_skill(room, pid)
                value = max(0, min(100, round(random.gauss(room.target, sigma))))
                room.guesses[pid] = value
                room.locked.add(pid)
                if len(room.locked) >= len(room.guessers()):
                    resolve_round(room)
                acted = True
            if acted:
                await broadcast(room)
    except Exception as e:
        print(f"[bot {pid}] move failed: {e!r}", flush=True)


async def handle_action(room: Room, pid: str, action: dict[str, Any]) -> str | None:
    player = room.players.get(pid)
    if not player:
        return "Player not found"
    kind = action.get("action")

    if kind == "add_bot":
        if pid != room.host_id:
            return "Only the host can add bots"
        if room.phase != "lobby":
            return "Bots can only join in the lobby"
        if len(room.players) >= 8:
            return "Room is full (8 players maximum)"
        used = {p.name for p in room.player_list}
        name = next((n for n in BOT_NAMES if n not in used), None)
        if not name:
            return "No bot names left"
        bot_id = new_id("b")
        room.players[bot_id] = Player(id=bot_id, name=name, is_bot=True)
        return None

    if kind == "kick_bot":
        if pid != room.host_id:
            return "Only the host can remove bots"
        target_id = str(action.get("target", ""))
        bot = room.players.get(target_id)
        if not bot or not bot.is_bot:
            return "That's not a bot"
        del room.players[target_id]
        return None

    if kind == "start_match":
        if pid != room.host_id:
            return "Only the host can start"
        if room.phase != "lobby":
            return "The match has already started"
        if len(room.players) < 2:
            return "Invite at least one friend first (best with 3)"
        room.deck = []
        room.scores = {}
        room.psychic_idx = 0
        room.round_number = 0
        start_round(room)
        schedule_bots(room)
        return None

    if kind == "ready":
        # Psychic confirms they've seen where the wheel landed; round goes live on the call
        if room.phase != "psychic":
            return "Not waiting on the psychic"
        if pid != room.psychic_id:
            return "Only the Psychic can start the round"
        room.phase = "guessing"
        room.event_message = "Clue time — everyone else, set your dial."
        schedule_bots(room)
        return None

    if kind == "set_guess":
        if room.phase != "guessing":
            return "The dial isn't open yet"
        if pid == room.psychic_id:
            return "You're the Psychic this round — sit back"
        if pid in room.locked:
            return "Already locked in"
        try:
            value = max(0, min(100, float(action.get("value"))))
        except (TypeError, ValueError):
            return "Invalid dial value"
        room.guesses[pid] = value
        return None

    if kind == "lock_guess":
        if room.phase != "guessing":
            return "The dial isn't open yet"
        if pid == room.psychic_id:
            return "You're the Psychic this round — sit back"
        if pid not in room.guesses:
            return "Set your dial first"
        room.locked.add(pid)
        if len(room.locked) >= len(room.guessers()):
            resolve_round(room)
        return None

    if kind == "force_reveal":
        if pid != room.host_id:
            return "Only the host can force the reveal"
        if room.phase != "guessing":
            return "Nothing to reveal yet"
        resolve_round(room)
        return None

    if kind == "skip_round":
        if pid != room.host_id:
            return "Only the host can skip"
        if room.phase not in ("psychic", "guessing"):
            return "Nothing to skip"
        room.psychic_idx += 1
        start_round(room)
        schedule_bots(room)
        return None

    if kind == "next_round":
        if pid != room.host_id:
            return "Only the host runs the next round"
        if room.phase != "reveal":
            return "Finish this round first"
        room.psychic_idx += 1
        start_round(room)
        schedule_bots(room)
        return None

    if kind == "rematch":
        if pid != room.host_id:
            return "Only the host can start the rematch"
        if room.phase != "match_over":
            return "Finish the match first"
        room.deck = []
        room.scores = {}
        room.psychic_idx = 0
        room.round_number = 0
        start_round(room)
        schedule_bots(room)
        return None

    if kind == "reset":
        if pid != room.host_id:
            return "Only the host can reset the room"
        room.phase = "lobby"
        room.round_number = 0
        room.scores = {}
        room.left = room.right = ""
        room.target = 0
        room.guesses = {}
        room.locked = set()
        room.last_reveal = None
        room.psychic_id = None
        room.bot_scheduled = {}
        room.event_message = "Back in the lobby."
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
