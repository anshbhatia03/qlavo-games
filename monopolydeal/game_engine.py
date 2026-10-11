from __future__ import annotations

import random
import secrets
from dataclasses import dataclass, field
from typing import Any

SUPER_ADMIN_NAMES = {"Ansh Mutthal", "Micky D", "KK"}
COLORS = ["brown", "light blue", "pink", "orange", "red", "yellow", "green", "dark blue", "railroad", "utility"]
COLOR_LABELS = {c: c.title() for c in COLORS}
PROPERTY_DATA = {
    "brown": [("Mediterranean Avenue", 1), ("Baltic Avenue", 1)],
    "light blue": [("Oriental Avenue", 1), ("Vermont Avenue", 1), ("Connecticut Avenue", 1)],
    "pink": [("St. Charles Place", 2), ("States Avenue", 2), ("Virginia Avenue", 2)],
    "orange": [("St. James Place", 2), ("Tennessee Avenue", 2), ("New York Avenue", 2)],
    "red": [("Kentucky Avenue", 3), ("Indiana Avenue", 3), ("Illinois Avenue", 3)],
    "yellow": [("Atlantic Avenue", 3), ("Ventnor Avenue", 3), ("Marvin Gardens", 3)],
    "green": [("Pacific Avenue", 4), ("North Carolina Avenue", 4), ("Pennsylvania Avenue", 4)],
    "dark blue": [("Park Place", 4), ("Boardwalk", 4)],
    "railroad": [("Reading Railroad", 2), ("Pennsylvania Railroad", 2), ("B. & O. Railroad", 2), ("Short Line", 2)],
    "utility": [("Electric Company", 2), ("Water Works", 2)],
}
SET_SIZE = {color: len(items) for color, items in PROPERTY_DATA.items()}
RENT_TABLE = {"brown": [1, 2], "light blue": [1, 2, 3], "pink": [1, 2, 4], "orange": [1, 3, 5], "red": [2, 3, 6], "yellow": [2, 4, 6], "green": [2, 4, 7], "dark blue": [3, 8], "railroad": [1, 2, 3, 4], "utility": [1, 2]}
WILD_DATA = [
    ("Light Blue / Brown Wild", ["light blue", "brown"], 1, 1), ("Light Blue / Railroad Wild", ["light blue", "railroad"], 1, 1),
    ("Pink / Orange Wild", ["pink", "orange"], 2, 2), ("Red / Yellow Wild", ["red", "yellow"], 3, 2),
    ("Dark Blue / Green Wild", ["dark blue", "green"], 4, 1), ("Green / Railroad Wild", ["green", "railroad"], 2, 1),
    ("Railroad / Utility Wild", ["railroad", "utility"], 2, 1), ("Rainbow Wild", COLORS, 0, 2),
]


class RuleError(Exception):
    pass


def card_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(5)}"


def is_super_admin(name: str) -> bool:
    return name in {"Ansh Mutthal", "Micky D", "KK"}


def make_deck() -> list[dict[str, Any]]:
    deck: list[dict[str, Any]] = []
    for value, count in [(1, 6), (2, 5), (3, 3), (4, 3), (5, 2), (10, 1)]:
        for _ in range(count):
            deck.append({"id": card_id("money"), "kind": "money", "title": f"${value}M", "value": value})
    for color, props in PROPERTY_DATA.items():
        for name, value in props:
            deck.append({"id": card_id("prop"), "kind": "property", "title": name, "value": value, "colors": [color], "color": color, "set_size": SET_SIZE[color], "rent": RENT_TABLE[color], "wild": False})
    for title, colors, value, count in WILD_DATA:
        for _ in range(count):
            deck.append({"id": card_id("wild"), "kind": "property", "title": title, "value": value, "colors": colors, "color": None, "wild": True, "set_size": None})
    for title, value, count in [("Deal Breaker", 5, 2), ("Just Say No", 4, 3), ("Sly Deal", 3, 3), ("Forced Deal", 3, 3), ("Debt Collector", 3, 3), ("It's My Birthday", 2, 3), ("Pass Go", 1, 10), ("House", 3, 3), ("Hotel", 4, 2), ("Double The Rent", 1, 2)]:
        kind = "house" if title == "House" else "hotel" if title == "Hotel" else "action"
        for _ in range(count):
            deck.append({"id": card_id("act"), "kind": kind, "title": title, "value": value})
    for title, colors, value, count in [("Brown / Light Blue Rent", ["brown", "light blue"], 1, 2), ("Pink / Orange Rent", ["pink", "orange"], 1, 2), ("Red / Yellow Rent", ["red", "yellow"], 2, 2), ("Dark Blue / Green Rent", ["dark blue", "green"], 2, 2), ("Railroad / Utility Rent", ["railroad", "utility"], 1, 2), ("Wild Rent", COLORS, 3, 3)]:
        for _ in range(count):
            deck.append({"id": card_id("rent"), "kind": "rent", "title": title, "value": value, "colors": colors, "wild_rent": len(colors) == len(COLORS)})
    return deck


def public_card(card: dict[str, Any]) -> dict[str, Any]:
    keys = {"id", "kind", "title", "value", "colors", "color", "wild", "assigned_color", "set_size", "rent", "house", "hotel"}
    return {k: v for k, v in card.items() if k in keys}


def card_value(card: dict[str, Any]) -> int:
    return int(card.get("value", 0))


def cash_card(card: dict[str, Any]) -> dict[str, Any]:
    value = card_value(card)
    return {"id": card["id"], "kind": "money", "title": f"${value}M", "value": value}


@dataclass
class Player:
    id: str
    name: str
    host: bool = False
    connected: bool = False
    super_admin: bool = False
    hand: list[dict[str, Any]] = field(default_factory=list)
    bank: list[dict[str, Any]] = field(default_factory=list)
    properties: list[dict[str, Any]] = field(default_factory=list)
    buildings: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GameState:
    players: dict[str, Player]
    host_id: str
    draw: list[dict[str, Any]]
    discard: list[dict[str, Any]] = field(default_factory=list)
    reserved: list[dict[str, Any]] = field(default_factory=list)
    phase: str = "lobby"
    current_id: str | None = None
    turn_number: int = 0
    plays_left: int = 0
    pending: dict[str, Any] | None = None
    event_log: list[str] = field(default_factory=list)
    winner_id: str | None = None
    play_sequence: int = 0
    last_play: dict[str, Any] | None = None

    @property
    def player_list(self) -> list[Player]:
        return list(self.players.values())


class GameEngine:
    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)

    def new_game(self, specs: list[dict[str, Any]]) -> GameState:
        if not 2 <= len(specs) <= 5:
            raise RuleError("Monopoly Deal is for 2–5 players")
        ids = [str(x["id"]) for x in specs]
        if len(set(ids)) != len(ids):
            raise RuleError("Duplicate player id")
        players = {x["id"]: Player(x["id"], str(x["username"]), host=i == 0, super_admin=is_super_admin(str(x["username"]))) for i, x in enumerate(specs)}
        deck = make_deck(); self.rng.shuffle(deck)
        state = GameState(players, ids[0], deck, phase="playing", current_id=ids[0])
        for p in state.player_list: self._draw(state, p, 5)
        self._reserve_just_say_no(state)
        self._begin_turn(state, ids[0], first=True)
        state.event_log.insert(0, "The table is live. Everyone was dealt five cards.")
        return state

    def _reserve_just_say_no(self, state: GameState) -> None:
        admins = [p for p in state.player_list if p.super_admin]
        cards = [c for c in state.draw if c["title"] == "Just Say No"]
        state.draw = [c for c in state.draw if c["title"] != "Just Say No"]
        for player, card in zip(admins, cards):
            player.hand.append(card)
        state.reserved.extend(cards[len(admins):])

    def _draw(self, state: GameState, player: Player, count: int) -> None:
        for _ in range(count):
            if not state.draw and state.discard:
                self.rng.shuffle(state.discard); state.draw, state.discard = state.discard, []
            if not state.draw: return
            player.hand.append(state.draw.pop())

    def _begin_turn(self, state: GameState, player_id: str, *, first: bool = False) -> None:
        p = state.players[player_id]; state.current_id = player_id; state.turn_number += 0 if first else 1; state.plays_left = 3; state.pending = None
        count = 5 if not p.hand else 2; before = len(p.hand); self._draw(state, p, count); drawn = len(p.hand) - before
        state.event_log.append(f"{p.name} starts turn {state.turn_number} and draws {drawn} card{'s' if drawn != 1 else ''}.")

    def _next_player(self, state: GameState) -> str:
        ids = list(state.players); return ids[(ids.index(state.current_id) + 1) % len(ids)]

    def _finish_turn(self, state: GameState) -> None:
        p = state.players[state.current_id]
        if len(p.hand) > 7:
            count = len(p.hand) - 7; state.pending = {"type": "discard", "player_id": p.id, "count": count}; state.event_log.append(f"{p.name} must discard {count} card{'s' if count != 1 else ''}."); return
        self._begin_turn(state, self._next_player(state))

    def _hand_card(self, p: Player, cid: Any) -> dict[str, Any]:
        if not isinstance(cid, str): raise RuleError("Card id must be text")
        for c in p.hand:
            if c["id"] == cid: return c
        raise RuleError("That card is not in your hand")

    def _remove_hand(self, p: Player, cid: str) -> dict[str, Any]:
        for i, c in enumerate(p.hand):
            if c["id"] == cid:
                return p.hand.pop(i)
        raise RuleError("That card is not in your hand")

    def _card_from_table(self, p: Player, cid: Any) -> tuple[str, dict[str, Any]]:
        if not isinstance(cid, str): raise RuleError("Card id must be text")
        for zone, cards in (("bank", p.bank), ("property", p.properties)):
            for c in cards:
                if c["id"] == cid: return zone, c
        raise RuleError("That table card is not yours")

    def _complete_sets(self, p: Player) -> list[str]:
        out = []
        for color in COLORS:
            cards = [c for c in p.properties if c.get("assigned_color") == color]
            if len(cards) >= SET_SIZE[color] and any(not c.get("wild") and c.get("color") == color for c in cards): out.append(color)
        return out

    def _set_cards(self, p: Player, color: str) -> list[dict[str, Any]]:
        return [c for c in p.properties if c.get("assigned_color") == color]

    def _property_rent(self, p: Player, color: str) -> int:
        cards = self._set_cards(p, color)
        if not cards or not any(not c.get("wild") and c.get("color") == color for c in cards): return 0
        total = RENT_TABLE[color][min(len(cards), len(RENT_TABLE[color])) - 1]
        if color in self._complete_sets(p):
            total += sum(3 if b.get("kind") == "house" else 4 for b in p.buildings if b.get("assigned_color") == color and b.get("active", True))
            for c in cards: total += 3 if c.get("house") else 0; total += 4 if c.get("hotel") else 0
        return total

    def _recompute_flags(self, p: Player) -> None:
        complete = set(self._complete_sets(p))
        for b in p.buildings:
            b["active"] = b.get("assigned_color") in complete
        for c in p.properties:
            if c.get("assigned_color") not in complete: c.pop("house", None); c.pop("hotel", None)

    def _announce_play(self, state: GameState, player: Player, cards: list[dict[str, Any]], verb: str = "played") -> None:
        state.play_sequence += 1
        state.last_play = {"sequence": state.play_sequence, "player_id": player.id, "player_name": player.name, "verb": verb, "cards": [public_card(c) for c in cards]}

    def _check_win(self, state: GameState, p: Player) -> None:
        cash_total = sum(card_value(c) for c in p.bank)
        if len(self._complete_sets(p)) >= 3 and cash_total >= 10:
            state.phase = "game_over"; state.winner_id = p.id; state.pending = None; state.event_log.append(f"{p.name} wins with three complete property sets and $10M cash.")

    def _start_response(self, state: GameState, action: dict[str, Any], targets: list[str]) -> None:
        targets = [x for x in targets if x in state.players and x != action["actor_id"]]
        actor = state.players[action["actor_id"]]
        if not actor.super_admin:
            targets += [p.id for p in state.player_list if p.super_admin and p.id != actor.id]
            targets = list(dict.fromkeys(targets))
        if not targets: self._apply_effect(state, action, []); return
        state.pending = {"type": "response", "action": action, "queue": targets, "denied": [], "target_id": None, "mode": None, "counter_player_id": None}; self._advance_response(state)

    def _advance_response(self, state: GameState) -> None:
        p = state.pending
        if not p or p["type"] != "response" or p["target_id"] is not None: return
        while p["queue"]:
            tid = p["queue"].pop(0); target = state.players[tid]
            actor = state.players[p["action"]["actor_id"]]
            if target.super_admin and not actor.super_admin:
                p["target_id"] = tid; p["mode"] = "override"; p["counter_player_id"] = actor.id; return
            p["action"].setdefault("approved", []).append(tid)
        action = p["action"]; self._apply_effect(state, action, [x for x in action.get("targets", []) if x in action.get("approved", [])])

    def _respond(self, state: GameState, pid: str, choice: str) -> None:
        p = state.pending; target_id = p.get("target_id") if p else None
        if not p or p["type"] != "response": raise RuleError("There is no action waiting for a response")
        expected = target_id if p["mode"] in {"target", "override"} else p.get("counter_player_id")
        if pid != expected: raise RuleError("Waiting for another player")
        if choice == "allow":
            if p["mode"] in {"target", "override"} and target_id in p["action"].get("targets", []): p["action"].setdefault("approved", []).append(target_id)
            elif p["mode"] == "counter" and p.get("admin_denied"):
                self._complete_action(state, p["action"]); return
            p["target_id"] = p["mode"] = p["counter_player_id"] = None; self._advance_response(state); return
        if choice != "just_say_no": raise RuleError("Unknown response")
        player = state.players[pid]; jsn = next((c for c in player.hand if c["title"] == "Just Say No"), None)
        actor = state.players[p["action"]["actor_id"]]
        if not player.super_admin or actor.super_admin: raise RuleError("That response is not available")
        jsn = next((c for c in player.hand if c["title"] == "Just Say No"), None)
        virtual = jsn or {"id": f"virtual-jsn-{player.id}", "kind": "action", "title": "Just Say No", "value": 4}
        self._announce_play(state, player, [virtual])
        if p["mode"] == "override": p["mode"] = "counter"; p["counter_player_id"] = actor.id; p["admin_denied"] = True; state.event_log.append(f"{player.name} played Just Say No.")
        else: raise RuleError("There is no available Just Say No response")

    def _start_payment(self, state: GameState, action: dict[str, Any], debts: list[dict[str, Any]]) -> None:
        debts = [d for d in debts if d["amount"] > 0]
        if not debts: self._complete_action(state, action); return
        state.pending = {"type": "payment", "action": action, "queue": debts, "debt": debts[0]}; self._auto_no_assets(state)

    def _auto_no_assets(self, state: GameState) -> None:
        while state.pending and state.pending["type"] == "payment":
            d = state.pending["debt"]; payer = state.players[d["payer_id"]]
            if payer.bank or payer.properties: return
            state.event_log.append(f"{payer.name} has no table cards and pays nothing."); state.pending["queue"].pop(0)
            if not state.pending["queue"]: self._complete_action(state, state.pending["action"]); return
            state.pending["debt"] = state.pending["queue"][0]

    def _pay(self, state: GameState, pid: str, card_ids: Any) -> None:
        p = state.pending; d = p["debt"] if p else None
        if not p or p["type"] != "payment" or not d or d["payer_id"] != pid: raise RuleError("You do not owe a payment right now")
        if not isinstance(card_ids, list) or len(set(card_ids)) != len(card_ids): raise RuleError("Choose distinct table cards")
        payer = state.players[pid]; receiver = state.players[d["receiver_id"]]; selected = [self._card_from_table(payer, cid) for cid in card_ids]
        total = sum(card_value(c) for _, c in selected)
        available = payer.bank + payer.properties
        available_total = sum(card_value(c) for c in available)
        if total < d["amount"] and total != available_total: raise RuleError("If you cannot cover the debt, select all cards in front of you")
        for zone, c in selected:
            if zone == "property":
                color = c.get("assigned_color")
                for b in payer.buildings:
                    if b.get("assigned_color") == color: b["active"] = False
            (payer.bank if zone == "bank" else payer.properties).remove(c)
            if zone == "bank": receiver.bank.append(c)
            else:
                received = dict(c, assigned_color=c.get("assigned_color") or c.get("color")); received.pop("house", None); received.pop("hotel", None); receiver.properties.append(received)
        self._recompute_flags(payer); self._recompute_flags(receiver)
        self._announce_play(state, payer, [c for _, c in selected], "paid")
        state.event_log.append(f"{payer.name} paid {receiver.name} ${total}M."); p["queue"].pop(0)
        if p["queue"]: p["debt"] = p["queue"][0]; self._auto_no_assets(state)
        else: self._complete_action(state, p["action"])

    def _complete_action(self, state: GameState, action: dict[str, Any]) -> None:
        state.pending = None; self._check_win(state, state.players[action["actor_id"]])

    def _apply_effect(self, state: GameState, action: dict[str, Any], approved: list[str]) -> None:
        actor = state.players[action["actor_id"]]; kind = action["kind"]
        if kind in {"deal_breaker", "sly_deal", "forced_deal", "debt_collector"} and action.get("target_id") not in approved:
            state.event_log.append(f"{actor.name}'s {kind.replace('_', ' ')} was cancelled.")
            self._complete_action(state, action)
            return
        if kind == "deal_breaker":
            target = state.players[action["target_id"]]; color = action["color"]; moving = self._set_cards(target, color)
            if color not in self._complete_sets(target): raise RuleError("That set is no longer complete")
            target.properties = [c for c in target.properties if c not in moving]; actor.properties.extend(dict(c) for c in moving)
            for c in actor.properties:
                if c["id"] in {x["id"] for x in moving}: c["assigned_color"] = color
            moved_buildings = [b for b in target.buildings if b.get("assigned_color") == color]
            target.buildings = [b for b in target.buildings if b.get("assigned_color") != color]
            actor.buildings.extend(dict(b, assigned_color=color, active=True) for b in moved_buildings)
            self._recompute_flags(target); self._recompute_flags(actor); state.event_log.append(f"{actor.name} took {COLOR_LABELS[color]} from {target.name} with Deal Breaker."); self._complete_action(state, action)
        elif kind == "sly_deal":
            target = state.players[action["target_id"]]; c = next((x for x in target.properties if x["id"] == action["property_id"]), None)
            if not c or c.get("assigned_color") in self._complete_sets(target): raise RuleError("That property is no longer available")
            target.properties.remove(c); actor.properties.append(dict(c)); self._recompute_flags(target); state.event_log.append(f"{actor.name} stole {c['title']} from {target.name}."); self._complete_action(state, action)
        elif kind == "forced_deal":
            target = state.players[action["target_id"]]; mine = next((c for c in actor.properties if c["id"] == action["my_property_id"]), None); theirs = next((c for c in target.properties if c["id"] == action["their_property_id"]), None)
            if not mine or not theirs: raise RuleError("One of those properties is no longer available")
            if mine.get("assigned_color") in self._complete_sets(actor) or theirs.get("assigned_color") in self._complete_sets(target): raise RuleError("Forced Deal cannot touch a complete set")
            actor.properties.remove(mine); target.properties.remove(theirs); actor.properties.append(dict(theirs)); target.properties.append(dict(mine)); self._recompute_flags(actor); self._recompute_flags(target); state.event_log.append(f"{actor.name} swapped property cards with {target.name}."); self._check_win(state, target); self._complete_action(state, action)
        elif kind in {"debt_collector", "birthday", "rent"}:
            if kind == "debt_collector": targets, amount = [action["target_id"]], 5
            elif kind == "birthday": targets, amount = approved, 2
            else: targets, amount = approved, action["amount"]
            debts = [{"payer_id": tid, "receiver_id": actor.id, "amount": amount} for tid in targets if tid != actor.id]
            self._start_payment(state, action, debts)
        else: self._complete_action(state, action)

    def _rent_action(self, state: GameState, actor: Player, card_ids: list[str], rent_card: dict[str, Any], color: str, target_id: str | None, multiplier: int = 1) -> None:
        if color not in rent_card.get("colors", []): raise RuleError("Choose a color shown on the Rent card")
        amount = self._property_rent(actor, color) * multiplier
        if amount <= 0: raise RuleError("You do not own a property in that color")
        targets = [target_id] if target_id else [p.id for p in state.player_list if p.id != actor.id]
        self._start_response(state, {"kind": "rent", "actor_id": actor.id, "card_ids": card_ids, "targets": targets, "approved": [], "amount": amount, "color": color}, targets)

    def apply(self, state: GameState, pid: str, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict): raise RuleError("Action must be an object")
        if state.phase == "game_over": raise RuleError("The game is over")
        p = state.players.get(pid)
        if not p: raise RuleError("Player not found")
        kind = payload.get("type") or payload.get("action")
        if state.pending:
            if state.pending["type"] == "response" and kind in {"allow", "allow_action", "just_say_no"}: self._respond(state, pid, "allow" if kind != "just_say_no" else "just_say_no"); return
            if state.pending["type"] == "payment" and kind in {"pay", "PAY"}: self._pay(state, pid, payload.get("card_ids")); return
            if state.pending["type"] == "discard" and pid == state.pending["player_id"] and kind in {"discard", "DISCARD"}:
                ids = payload.get("card_ids"); count = state.pending["count"]
                if not isinstance(ids, list) or len(ids) != count or len(set(ids)) != len(ids): raise RuleError(f"Discard exactly {count} cards")
                for cid in ids: state.discard.append(self._remove_hand(p, cid))
                state.pending = None; state.event_log.append(f"{p.name} discarded down to seven cards."); self._begin_turn(state, self._next_player(state)); return
            raise RuleError("Resolve the pending action first")
        if pid != state.current_id: raise RuleError("It is not your turn")
        if kind in {"end_turn", "END_TURN"}: self._finish_turn(state); return
        if kind in {"place_building", "PLACE_BUILDING"}:
            building = next((b for b in p.buildings if b.get("id") == payload.get("building_id")), None); color = payload.get("color")
            if not building or color not in self._complete_sets(p): raise RuleError("Choose one of your complete sets")
            others = [b for b in p.buildings if b is not building and b.get("assigned_color") == color and b.get("active", True)]
            if building.get("kind") == "house" and any(b.get("kind") == "house" for b in others): raise RuleError("A set can have only one House")
            if building.get("kind") == "hotel" and (not any(b.get("kind") == "house" for b in others) or any(b.get("kind") == "hotel" for b in others)): raise RuleError("A Hotel needs a House and each set can have only one")
            building["assigned_color"] = color; self._recompute_flags(p); return
        if kind in {"move_property", "MOVE_PROPERTY"}:
            c = next((x for x in p.properties if x["id"] == payload.get("card_id")), None); color = payload.get("color")
            if not c or not c.get("wild") or color not in c.get("colors", []): raise RuleError("Choose one of the colors on your Wild Property card")
            c["assigned_color"] = color; c["set_size"] = SET_SIZE[color]; self._recompute_flags(p); return
        if kind not in {"play_card", "PLAY_CARD", "bank_card", "BANK_CARD"}: raise RuleError("Unknown action")
        if state.plays_left <= 0: raise RuleError("You have used all three plays")
        card = self._hand_card(p, payload.get("card_id")); cid = card["id"]
        if kind in {"bank_card", "BANK_CARD"} or payload.get("zone") == "bank":
            if card["kind"] == "property": raise RuleError("Property cards cannot be converted to cash")
            p.hand.remove(card); converted = cash_card(card); p.bank.append(converted); state.plays_left -= 1; self._announce_play(state, p, [card], "converted to cash"); state.event_log.append(f"{p.name} converted {card['title']} into {converted['title']} cash."); self._check_win(state, p); return
        if card["kind"] == "money": p.hand.remove(card); p.bank.append(card); state.plays_left -= 1; self._announce_play(state, p, [card], "played to cash"); state.event_log.append(f"{p.name} banked {card['title']}."); self._check_win(state, p); return
        if card["kind"] == "property":
            color = payload.get("color") or card.get("color")
            if color not in card.get("colors", []): raise RuleError("Choose a color shown on that Property card")
            p.hand.remove(card); card["assigned_color"] = color; card["set_size"] = SET_SIZE[color]; p.properties.append(card); state.plays_left -= 1; self._announce_play(state, p, [card], "played to properties"); state.event_log.append(f"{p.name} played {card['title']} as {COLOR_LABELS[color]}."); self._check_win(state, p); return
        if card["title"] == "Pass Go": p.hand.remove(card); state.discard.append(card); state.plays_left -= 1; self._announce_play(state, p, [card]); self._draw(state, p, 2); state.event_log.append(f"{p.name} played Pass Go and drew two cards."); return
        if card["kind"] in {"house", "hotel"}:
            color = payload.get("color"); sets = self._complete_sets(p); set_cards = self._set_cards(p, color) if color in sets else []
            if color not in sets or any(x.get("house") or x.get("hotel") for x in set_cards): raise RuleError("Choose a complete set without that building")
            if card["kind"] == "hotel" and not any(x.get("house") for x in set_cards): raise RuleError("A Hotel needs a House")
            p.hand.remove(card); p.buildings.append({"id": card["id"], "kind": card["kind"], "title": card["title"], "value": card["value"], "assigned_color": color, "active": True}); state.plays_left -= 1; self._announce_play(state, p, [card], "played to properties"); state.event_log.append(f"{p.name} added a {card['title']} to {COLOR_LABELS[color]}."); return
        if card["title"] == "Double The Rent":
            rent_card = self._hand_card(p, payload.get("rent_card_id"));
            if rent_card["kind"] != "rent" or state.plays_left < 2: raise RuleError("Double The Rent must be paired with a Rent card")
            color = payload.get("color"); target_id = payload.get("target_id"); p.hand.remove(card); p.hand.remove(rent_card); state.discard.extend([card, rent_card]); state.plays_left -= 2; self._announce_play(state, p, [card, rent_card]); self._rent_action(state, p, [cid, rent_card["id"]], rent_card, color, target_id, 2); return
        if card["kind"] == "rent":
            color = payload.get("color"); target_id = payload.get("target_id") if card.get("wild_rent") else None; p.hand.remove(card); state.discard.append(card); state.plays_left -= 1; self._announce_play(state, p, [card]); self._rent_action(state, p, [cid], card, color, target_id); return
        if card["title"] == "Just Say No": raise RuleError("Just Say No is played as a response")
        target_id = payload.get("target_id")
        if card["title"] in {"Deal Breaker", "Sly Deal", "Forced Deal", "Debt Collector"} and (not isinstance(target_id, str) or target_id not in state.players or target_id == pid): raise RuleError("Choose an opponent")
        action = {"actor_id": pid, "card_ids": [cid], "targets": [target_id] if target_id else [], "approved": []}
        if card["title"] == "Deal Breaker":
            color = payload.get("color");
            if color not in self._complete_sets(state.players[target_id]): raise RuleError("Choose one of that player's complete sets")
            action.update(kind="deal_breaker", target_id=target_id, color=color)
        elif card["title"] == "Sly Deal":
            target = state.players[target_id]; prop_id = payload.get("property_id"); prop = next((x for x in target.properties if x["id"] == prop_id), None)
            if not prop or prop.get("assigned_color") in self._complete_sets(target): raise RuleError("Choose a property outside a complete set")
            action.update(kind="sly_deal", target_id=target_id, property_id=prop_id)
        elif card["title"] == "Forced Deal":
            target = state.players[target_id]; mine = next((x for x in p.properties if x["id"] == payload.get("my_property_id")), None); theirs = next((x for x in target.properties if x["id"] == payload.get("their_property_id")), None)
            if not mine or not theirs or mine.get("assigned_color") in self._complete_sets(p) or theirs.get("assigned_color") in self._complete_sets(target): raise RuleError("Both properties must be outside complete sets")
            action.update(kind="forced_deal", target_id=target_id, my_property_id=mine["id"], their_property_id=theirs["id"])
        elif card["title"] == "Debt Collector": action.update(kind="debt_collector", target_id=target_id)
        elif card["title"] == "It's My Birthday": action.update(kind="birthday", targets=[x.id for x in state.player_list if x.id != pid])
        else: raise RuleError("That action needs a supported option")
        p.hand.remove(card); state.discard.append(card); state.plays_left -= 1; self._announce_play(state, p, [card]); self._start_response(state, action, action["targets"])

    def _pending_view(self, state: GameState, viewer_id: str) -> dict[str, Any] | None:
        p = state.pending
        if not p: return None
        if p["type"] == "response":
            a = p["action"]; tid = p.get("target_id"); expected = tid if p.get("mode") in {"target", "override"} else p.get("counter_player_id")
            return {"type": "response", "kind": a.get("kind"), "actor_id": a["actor_id"], "actor_name": state.players[a["actor_id"]].name, "target_id": tid, "target_name": state.players[tid].name if tid else "", "mode": p.get("mode") if viewer_id == expected else None, "can_respond": viewer_id == expected, "can_just_say_no": viewer_id == expected and p.get("mode") == "override"}
        if p["type"] == "payment":
            d = p["debt"]; payer = state.players[d["payer_id"]]
            return {"type": "payment", "payer_id": d["payer_id"], "payer_name": payer.name, "receiver_name": state.players[d["receiver_id"]].name, "amount": d["amount"], "can_pay": viewer_id == payer.id, "pay_options": [public_card(c) for c in payer.bank + payer.properties] if viewer_id == payer.id else []}
        return {"type": "discard", "player_id": p["player_id"], "count": p["count"], "can_discard": viewer_id == p["player_id"]} if p["type"] == "discard" else None

    def snapshot(self, state: GameState, viewer_id: str) -> dict[str, Any]:
        viewer = state.players[viewer_id]
        def pv(p: Player) -> dict[str, Any]:
            return {"id": p.id, "name": p.name, "host": p.host, "connected": p.connected, "hand_count": len(p.hand), "bank_total": sum(card_value(c) for c in p.bank), "bank": [public_card(c) for c in p.bank], "properties": [public_card(c) for c in p.properties], "buildings": [public_card(b) for b in p.buildings], "complete_sets": self._complete_sets(p)}
        out = {"type": "state", "phase": state.phase, "viewer": viewer_id, "viewer_name": viewer.name, "is_host": viewer_id == state.host_id, "private_viewer": viewer.super_admin, "current_id": state.current_id, "current_name": state.players[state.current_id].name if state.current_id else "", "turn_number": state.turn_number, "plays_left": state.plays_left if viewer_id == state.current_id else None, "draw_count": len(state.draw), "discard_count": len(state.discard), "discard_top": public_card(state.discard[-1]) if state.discard else None, "your_hand": [public_card(c) for c in viewer.hand], "your_bank": [public_card(c) for c in viewer.bank], "your_properties": [public_card(c) for c in viewer.properties], "your_buildings": [public_card(b) for b in viewer.buildings], "your_complete_sets": self._complete_sets(viewer), "players": [pv(p) for p in state.player_list], "events": state.event_log[-30:], "winner_id": state.winner_id, "last_play": state.last_play, "pending": self._pending_view(state, viewer_id)}
        if viewer.super_admin: out["private_hands"] = {p.id: {"name": p.name, "hand": [public_card(c) for c in p.hand]} for p in state.player_list if not p.super_admin}
        return out

    def validate_deck(self) -> dict[str, int]:
        deck = make_deck(); return {"total": len(deck), "money": sum(c["kind"] == "money" for c in deck), "properties": sum(c["kind"] == "property" and not c.get("wild") for c in deck), "wild_properties": sum(c["kind"] == "property" and c.get("wild") for c in deck), "actions": sum(c["kind"] in {"action", "house", "hotel"} for c in deck), "rent": sum(c["kind"] == "rent" for c in deck)}
