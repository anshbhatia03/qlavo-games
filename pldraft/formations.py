"""Formation slot layouts for PL Draft. Each formation maps XI slots to pitch coordinates.
Coordinates are (x%, y%) on a vertical pitch: y=0 own goal, y=100 opponent goal.
Slot ids encode role: GK, RB, LB, CB, CDM, CM, CAM, LW, RW, ST.
Back-3 vs back-4 flag drives the back3 fit bonus for CBs.
"""

FORMATIONS = {
    "4-2-3-1": {
        "back3": False,
        "slots": [
            ("GK", 50, 4),
            ("LB", 12, 26), ("CB", 37, 22), ("CB", 63, 22), ("RB", 88, 26),
            ("CDM", 35, 46), ("CDM", 65, 46),
            ("LW", 14, 66), ("CAM", 50, 62), ("RW", 86, 66),
            ("ST", 50, 88),
        ],
    },
    "4-3-3": {
        "back3": False,
        "slots": [
            ("GK", 50, 4),
            ("LB", 12, 26), ("CB", 37, 22), ("CB", 63, 22), ("RB", 88, 26),
            ("CDM", 50, 44), ("CM", 28, 56), ("CM", 72, 56),
            ("LW", 15, 80), ("ST", 50, 86), ("RW", 85, 80),
        ],
    },
    "4-4-2": {
        "back3": False,
        "slots": [
            ("GK", 50, 4),
            ("LB", 12, 26), ("CB", 37, 22), ("CB", 63, 22), ("RB", 88, 26),
            ("LW", 14, 50), ("CM", 38, 48), ("CM", 62, 48), ("RW", 86, 50),
            ("ST", 38, 84), ("ST", 62, 84),
        ],
    },
    "4-4-2-diamond": {
        "back3": False,
        "slots": [
            ("GK", 50, 4),
            ("LB", 12, 26), ("CB", 37, 22), ("CB", 63, 22), ("RB", 88, 26),
            ("CDM", 50, 42), ("LW", 22, 56), ("RW", 78, 56), ("CAM", 50, 66),
            ("ST", 38, 86), ("ST", 62, 86),
        ],
    },
    "4-1-4-1": {
        "back3": False,
        "slots": [
            ("GK", 50, 4),
            ("LB", 12, 26), ("CB", 37, 22), ("CB", 63, 22), ("RB", 88, 26),
            ("CDM", 50, 40),
            ("LW", 14, 58), ("CM", 38, 54), ("CM", 62, 54), ("RW", 86, 58),
            ("ST", 50, 86),
        ],
    },
    "3-4-3": {
        "back3": True,
        "slots": [
            ("GK", 50, 4),
            ("CB", 28, 22), ("CB", 50, 20), ("CB", 72, 22),
            ("LB", 10, 48), ("CM", 38, 48), ("CM", 62, 48), ("RB", 90, 48),
            ("LW", 20, 78), ("ST", 50, 86), ("RW", 80, 78),
        ],
    },
    "3-5-2": {
        "back3": True,
        "slots": [
            ("GK", 50, 4),
            ("CB", 28, 22), ("CB", 50, 20), ("CB", 72, 22),
            ("LB", 10, 46), ("CDM", 50, 44), ("RB", 90, 46),
            ("LW", 24, 60), ("CAM", 50, 58), ("RW", 76, 60),
            ("ST", 38, 86), ("ST", 62, 86),
        ],
    },
    "3-4-2-1": {
        "back3": True,
        "slots": [
            ("GK", 50, 4),
            ("CB", 28, 22), ("CB", 50, 20), ("CB", 72, 22),
            ("LB", 10, 48), ("CM", 38, 48), ("CM", 62, 48), ("RB", 90, 48),
            ("CAM", 38, 70), ("CAM", 62, 70),
            ("ST", 50, 88),
        ],
    },
    "4-5-1": {
        "back3": False,
        "slots": [
            ("GK", 50, 4),
            ("LB", 12, 26), ("CB", 37, 22), ("CB", 63, 22), ("RB", 88, 26),
            ("LW", 12, 52), ("CDM", 38, 44), ("CM", 50, 52), ("CDM", 62, 44), ("RW", 88, 52),
            ("ST", 50, 86),
        ],
    },
    "5-3-2": {
        "back3": True,
        "slots": [
            ("GK", 50, 4),
            ("LB", 6, 34), ("CB", 28, 20), ("CB", 50, 18), ("CB", 72, 20), ("RB", 94, 34),
            ("CM", 30, 50), ("CDM", 50, 46), ("CM", 70, 50),
            ("ST", 38, 82), ("ST", 62, 82),
        ],
    },
}

FORMATION_NAMES = list(FORMATIONS.keys())


def slots_for(name):
    """Return list of dicts: {role, x, y, idx} for a formation name."""
    out = []
    seen = {}
    for role, x, y in FORMATIONS[name]["slots"]:
        seen[role] = seen.get(role, 0)
        out.append({"role": role, "x": x, "y": y, "idx": seen[role]})
        seen[role] += 1
    return out


def back3(name):
    return FORMATIONS[name]["back3"]


def auto_assign(players, formation):
    """Greedy assignment: given a list of players (each with hidden fit dict) and a
    formation, return {player_id: slot_index} maximising total fit.
    Greedy: repeatedly take the (player, slot) pair with the highest fit score.
    Ties broken by player ovr then slot order.
    """
    slots = slots_for(formation)
    remaining = list(players)
    assign = {}
    used = set()
    pairs = []
    for si, slot in enumerate(slots):
        for p in remaining:
            f = p["fit"].get(slot["role"], 0)
            pairs.append((f, p["ovr"], -si, p["id"], si))
    pairs.sort(reverse=True)
    for f, ovr, nsi, pid, si in pairs:
        if pid in used or si in used:
            continue
        used.add(pid)
        used.add(si)
        assign[pid] = si
        if len(assign) == len(slots) or len(assign) == len(players):
            break
    return assign
