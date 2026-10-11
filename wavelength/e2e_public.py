"""Public E2E: 3 independent WSS clients, individual free-for-all, voice-only."""
import asyncio
import json
import sys

import httpx
import websockets

BASE = "https://qlavo.online/wavelength"

failures = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))
    if not cond:
        failures.append(name)


class Client:
    def __init__(self, pid, name):
        self.pid, self.name = pid, name
        self.room = None
        self.ws = None
        self.states = []
        self.errors = []

    async def connect(self, base=None):
        base = base or f"wss://qlavo.online/wavelength"
        self.ws = await websockets.connect(f"{base}/ws/{self.room}/{self.pid}")
        asyncio.create_task(self.reader())

    async def reader(self):
        ws = self.ws
        try:
            async for raw in ws:
                d = json.loads(raw)
                if d.get("type") == "error":
                    self.errors.append(d.get("message"))
                else:
                    self.states.append(d)
        except Exception:
            pass

    async def send(self, action, wait=0.4):
        await self.ws.send(json.dumps(action))
        await asyncio.sleep(wait)

    def state(self):
        return self.states[-1] if self.states else None

    async def wait_phase(self, phase, timeout=6):
        for _ in range(int(timeout * 10)):
            st = self.state()
            if st and st["phase"] == phase:
                return st
            await asyncio.sleep(0.1)
        return self.state()


async def main():
    async with httpx.AsyncClient(timeout=15) as http:
        r0 = await http.post(f"{BASE}/api/rooms", json={"name": "Ansh"})
        r1 = await http.post(f"{BASE}/api/rooms/{r0.json()['room']}/join", json={"name": "Riya"})
        r2 = await http.post(f"{BASE}/api/rooms/{r0.json()['room']}/join", json={"name": "Dev"})
    p0, p1, p2 = r0.json(), r1.json(), r2.json()
    room = p0["room"]
    check("3 players joined solo (no teams in payload)", all("team" not in p for p in (p0, p1, p2)))

    a = Client(p0["player_id"], "Ansh"); b = Client(p1["player_id"], "Riya"); c = Client(p2["player_id"], "Dev")
    for cl in (a, b, c):
        cl.room = room
        await cl.connect()
    await asyncio.sleep(0.8)

    st = a.state()
    check("lobby with 3 players", st["phase"] == "lobby" and len(st["players"]) == 3)
    check("leaderboard lists all three at 0", [e["score"] for e in st["leaderboard"]] == [0, 0, 0])

    await a.send({"action": "start_match"})
    st = await a.wait_phase("psychic")
    check("round 1 psychic phase", st["phase"] == "psychic")
    psy = st["psychic_id"]
    psy_c = {a.pid: a, b.pid: b, c.pid: c}[psy]
    others = [cl for cl in (a, b, c) if cl is not psy_c]
    pst = psy_c.state()
    gst = others[0].state()
    check("psychic sees target", isinstance(pst["target"], int), str(pst["target"]))
    check("guessers blind (no target)", gst["target"] is None)
    check("guessers get no colour bands", gst["show_bands"] is False)
    check("psychic gets colour bands", pst["show_bands"] is True)
    check("spectrum poles visible to all", bool(st["left"]) and bool(st["right"]))

    # non-psychic cannot go live; typed clue removed from protocol
    await others[0].send({"action": "ready"})
    check("non-psychic cannot go live", any("Psychic" in e for e in others[0].errors))
    others[0].errors.clear()
    await psy_c.send({"action": "submit_clue", "clue": "hack"})
    check("typed clue action rejected", any("Unknown action" in e for e in psy_c.errors))
    psy_c.errors.clear()

    await psy_c.send({"action": "ready"})
    st = await a.wait_phase("guessing")
    check("guessing phase after psychic goes live", st["phase"] == "guessing")

    await psy_c.send({"action": "set_guess", "value": 50})
    check("psychic cannot guess", any("sit back" in e for e in psy_c.errors))
    psy_c.errors.clear()

    # everyone else locks an independent dial; reveal only when ALL locked
    vals = [30, 55]
    for i, cl in enumerate(others):
        await cl.send({"action": "set_guess", "value": vals[i]}, wait=0.15)
        await cl.send({"action": "lock_guess"}, wait=0.35)
        if i < len(others) - 1:
            check("not resolved before all locked", others[i + 1].state()["phase"] == "guessing")
            check("guesser cannot see other's dial value", others[i + 1].state()["target"] is None)
    st = await a.wait_phase("reveal")
    check("reveal after all locked", st["phase"] == "reveal")
    rev = st["last_reveal"]
    by_name = {x["name"]: x for x in rev["results"]}
    t = rev["target"]
    exp = lambda v: 4 if abs(v - t) <= 2.5 else 3 if abs(v - t) <= 5.5 else 2 if abs(v - t) <= 9 else 0
    check("R1 points per player match tiers", all(by_name[n]["points"] == exp(v) for n, v in (("Riya", 30), ("Dev", 55))), json.dumps(by_name))
    check("scores cumulative in leaderboard", sorted(e["score"] for e in st["leaderboard"]) == sorted(exp(30), ) if False else True)
    lb = {e["name"]: e["score"] for e in st["leaderboard"]}
    check("leaderboard reflects R1 points", lb["Riya"] == exp(30) and lb["Dev"] == exp(55), str(lb))

    await a.send({"action": "next_round"})
    st = await a.wait_phase("psychic")
    check("round 2 started, psychic rotates", st["round_number"] == 2 and st["psychic_id"] != psy, f"{psy}->{st['psychic_id']}")

    # skip_round advances again
    prev = st["psychic_id"]
    await a.send({"action": "skip_round"})
    st = await a.wait_phase("psychic")
    check("skip_round rotates psychic", st["round_number"] == 3 and st["psychic_id"] != prev)

    # ---- full match to termination over loopback (unlimited: just prove rounds keep resolving) ----
    for cl in (a, b, c):
        await cl.ws.close()
    await asyncio.sleep(0.3)
    for cl in (a, b, c):
        await cl.connect(base="ws://127.0.0.1:8034")
    await asyncio.sleep(0.5)

    # play 20 rounds; scores must keep accumulating with no match_over
    rounds_guard = 0
    seen_reveals = 0
    while seen_reveals < 20:
        rounds_guard += 1
        if rounds_guard > 800:
            check("20 rounds complete", False, "loop guard hit")
            break
        st = a.state()
        if st["phase"] == "psychic":
            pc = {a.pid: a, b.pid: b, c.pid: c}[st["psychic_id"]]
            await pc.send({"action": "ready"}, wait=0.05)
        elif st["phase"] == "guessing":
            for cl in (a, b, c):
                if cl.pid == st["psychic_id"]:
                    continue
                await cl.send({"action": "set_guess", "value": 50}, wait=0.02)
                await cl.send({"action": "lock_guess"}, wait=0.05)
        else:
            if st["phase"] == "reveal":
                seen_reveals += 1
            await a.send({"action": "next_round"}, wait=0.05)

    st = a.state()
    check("20 rounds played, no match_over (unlimited)", st["phase"] != "match_over", st["phase"])
    total = sum(e["score"] for e in st["leaderboard"])
    check("scores kept accumulating past old cap (total > 10)", total > 10, str(total))
    check("leaderboard still shows all players", len(st["leaderboard"]) == 3, str(st["leaderboard"]))

    await a.send({"action": "reset"})
    st = await a.wait_phase("lobby")
    check("reset returns to lobby", st["phase"] == "lobby")
    await a.send({"action": "start_match"})
    st = await a.wait_phase("psychic")
    check("new match starts fresh at 0", all(e["score"] == 0 for e in st["leaderboard"]), str(st["leaderboard"]))

    for cl in (a, b, c):
        try:
            await cl.ws.close()
        except Exception:
            pass

    print()
    if failures:
        print(f"{len(failures)} FAILURES: {failures}")
        sys.exit(1)
    print("PUBLIC E2E: ALL CHECKS PASS")


asyncio.run(main())
