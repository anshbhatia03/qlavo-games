"""Deterministic engine fixtures for Wavelength (individual free-for-all, unlimited rounds). Run: python3 test_engine.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app import Room, Player, points_for_distance, resolve_round, state_for, start_round  # noqa: E402

failures = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


# --- scoring tiers (must match the drawn bands) ---
check("dist 0 -> 4 pts", points_for_distance(0) == 4)
check("dist 2.5 -> 4 pts", points_for_distance(2.5) == 4)
check("dist 2.6 -> 3 pts", points_for_distance(2.6) == 3)
check("dist 5.5 -> 3 pts", points_for_distance(5.5) == 3)
check("dist 5.6 -> 2 pts", points_for_distance(5.6) == 2)
check("dist 9.0 -> 2 pts", points_for_distance(9.0) == 2)
check("dist 9.1 -> 0 pts (miss)", points_for_distance(9.1) == 0)
check("dist 50 -> 0 pts (miss)", points_for_distance(50) == 0)


def make_room_3():
    room = Room(code="TEST", host_id="h")
    room.players = {
        "h": Player(id="h", name="Host"),
        "g1": Player(id="g1", name="G1"),
        "g2": Player(id="g2", name="G2"),
    }
    return room


# --- round lifecycle + secrecy ---
room = make_room_3()
room.deck = [["Cold", "Hot"]]
start_round(room)
check("phase psychic after start", room.phase == "psychic")
check("target clamped 10..90 so wedge fits", 10 <= room.target <= 90)
check("guessers are the other two", {p.id for p in room.guessers()} == {"g1", "g2"})
st_psy = state_for(room, "h")
st_g = state_for(room, "g1")
check("psychic sees target", isinstance(st_psy["target"], int))
check("guesser does NOT see target", st_g["target"] is None)
check("bands hidden from guesser", st_g["show_bands"] is False)
check("bands shown to psychic", st_psy["show_bands"] is True)

room.phase = "guessing"
st_g = state_for(room, "g1")
check("guesser blind while guessing", st_g["target"] is None and st_g["show_bands"] is False)

# --- resolution: independent scoring per player ---
room.guesses = {"g1": 42, "g2": 20}
room.target = 40
resolve_round(room)
rev = room.last_reveal
by_name = {r["name"]: r for r in rev["results"]}
check("g1 dist 2 -> +4", by_name["G1"]["points"] == 4 and room.scores["g1"] == 4)
check("g2 dist 20 -> +0 (miss)", by_name["G2"]["points"] == 0 and room.scores["g2"] == 0)
check("psychic scored nothing", "h" not in room.scores)

# --- unlimited: no match_over ever, scores just accumulate ---
room.phase = "guessing"
room.scores = {"h": 99, "g1": 3, "g2": 0}
room.guesses = {"g2": 10}
room.target = 10
resolve_round(room)
check("high score does NOT end match (unlimited)", room.phase == "reveal")
check("scores keep climbing past any cap", room.scores["h"] == 99)

# --- role guards ---
from app import handle_action  # noqa: E402
import inspect  # noqa: E402

src = inspect.getsource(handle_action)
check("no typed-clue action exists", "submit_clue" not in src)
check("set_guess blocked for psychic", "pid == room.psychic_id" in src)
check("lock resolves when all guessers locked", "len(room.locked) >= len(room.guessers())" in src)

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("ALL ENGINE FIXTURES PASS")
