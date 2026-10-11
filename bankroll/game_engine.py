"""Pure, server-authoritative Bankroll game engine.

No FastAPI, browser, or network imports live here. The transport owns rooms and
calls GameEngine.apply(state, player_id, action). Randomness is injected through
an isolated random.Random instance so simulations and tests can use a seed.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).parent
CONFIG = ROOT / "config"


@dataclass
class GameEvent:
    type: str
    actor_id: str | None = None
    target_id: str | None = None
    amount: int | None = None
    property_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    text: str = ""


@dataclass
class PropertyState:
    id: str
    kind: str
    name: str
    purchase_price: int = 0
    base_rent: int = 0
    rent_owned_2: int = 0
    color_group: str | None = None
    public_type: str | None = None
    rent_with_set: int = 0
    rent_building: tuple[int, int, int] = (0, 0, 0)
    rent_by_owned_count: tuple[int, ...] = ()
    building_price: int = 0
    owner_id: str | None = None
    building_level: int = 0
    icon: str = ""


@dataclass
class PlayerState:
    id: str
    username: str
    avatar: str = "●"
    color: str = "#f5b40e"
    cash: int = 0
    board_position: int = 0
    properties_owned: set[str] = field(default_factory=set)
    jail_turns_remaining: int = 0
    bankrupt: bool = False
    forfeited: bool = False
    connected: bool = True
    is_bot: bool = False
    wins: int = 0


@dataclass
class AuctionListing:
    seller_id: str
    property_id: str
    bids: dict[str, dict[str, Any]] = field(default_factory=dict)  # bidder_id -> {propertyId?, cash?}

    @property
    def id(self) -> str:
        return f"{self.seller_id}:{self.property_id}"


@dataclass
class AuctionState:
    initiator_id: str
    listings: list[AuctionListing] = field(default_factory=list)
    opted_out: set[str] = field(default_factory=set)
    quiet_cycles: int = 0  # watchdog bookkeeping: how often bots paused on silent humans


@dataclass
class GameState:
    phase: str = "LOBBY"
    turn_phase: str = "LOBBY"
    target_worth: int = 3000
    round_limit: int = 0
    current_round: int = 1
    turn_order: list[str] = field(default_factory=list)
    turn_index: int = 0
    last_roll: int | None = None
    last_path: list[int] = field(default_factory=list)
    last_roll_actor_id: str | None = None
    roll_sequence: int = 0
    extra_roll: bool = False
    pending_property_id: str | None = None
    pending_card: dict[str, Any] | None = None
    auction: AuctionState | None = None
    winner_id: str | None = None
    win_reason: str = ""
    players: dict[str, PlayerState] = field(default_factory=dict)
    properties: dict[str, PropertyState] = field(default_factory=dict)
    board_ids: list[str] = field(default_factory=list)
    events: list[GameEvent] = field(default_factory=list)


class RuleError(ValueError):
    """An action is not legal in the current authoritative state."""


class GameEngine:
    def __init__(self, config_dir: Path | str = CONFIG, seed: int | None = None):
        config_dir = Path(config_dir)
        self.balance = json.loads((config_dir / "balance.json").read_text())
        self.board_data = json.loads((config_dir / "board.json").read_text())
        self.card_data = json.loads((config_dir / "lucky_cards.json").read_text())
        self.rng = random.Random(seed)
        self._color_groups: dict[str, list[str]] = {}
        for raw in self.board_data:
            if raw.get("kind") == "city":
                self._color_groups.setdefault(raw["colorGroup"], []).append(raw["id"])

    # --------------------------------------------------------------- setup ----
    def new_game(
        self,
        players: Iterable[dict[str, Any]],
        target_worth: int = 3000,
        round_limit: int = 0,
    ) -> GameState:
        if target_worth not in self.balance["netWorthTargets"]:
            raise RuleError("invalid target worth")
        if round_limit not in self.balance["roundCaps"]:
            raise RuleError("invalid round limit")
        specs = list(players)
        if not 2 <= len(specs) <= 4:
            raise RuleError("Bankroll requires 2–4 players")
        ids = [str(p.get("id", "")) for p in specs]
        if any(not pid for pid in ids) or len(set(ids)) != len(ids):
            raise RuleError("player IDs must be non-empty and unique")
        order = ids
        self.rng.shuffle(order)
        bonuses = self.balance.get("turnOrderBonuses", [0, 0, 0, 0])
        state = GameState(
            phase="PLAYING",
            turn_phase="PROPERTY_MANAGEMENT",
            target_worth=target_worth,
            round_limit=round_limit,
            turn_order=order,
            board_ids=[x["id"] for x in self.board_data],
        )
        by_id = {str(spec["id"]): spec for spec in specs}
        start_position = next((i for i, raw in enumerate(self.board_data) if raw.get("kind") == "start"), 0)
        for seat_index, pid in enumerate(order):
            spec = by_id[pid]
            state.players[pid] = PlayerState(
                id=pid,
                username=spec.get("username", pid),
                avatar=spec.get("avatar", "●"),
                color=spec.get("color", ["#f5b40e", "#59b7e8", "#e05545", "#2fae62"][seat_index]),
                cash=int(self.balance["startingCash"] + bonuses[min(seat_index, len(bonuses) - 1)]),
                board_position=start_position,
                is_bot=bool(spec.get("isBot", False)),
            )
        for raw in self.board_data:
            state.properties[raw["id"]] = PropertyState(
                id=raw["id"], kind=raw["kind"], name=raw["name"],
                purchase_price=int(raw.get("purchasePrice", 0)),
                base_rent=int(raw.get("baseRent", 0)),
                rent_owned_2=int(raw.get("rentOwned2", raw.get("rentWithSet", raw.get("baseRent", 0)))),
                color_group=raw.get("colorGroup"), public_type=raw.get("publicType"),
                rent_with_set=int(raw.get("rentWithSet", raw.get("baseRent", 0))),
                rent_building=tuple(int(raw.get(f"rentBuilding{i}", 0)) for i in (1, 2, 3)),
                rent_by_owned_count=tuple(int(x) for x in raw.get("rentByOwnedCount", [])),
                building_price=int(raw.get("buildingPrice", 0)), icon=raw.get("icon", ""),
            )
        self._emit(state, "GAME_STARTED", text=f"Race to ${target_worth}. {self.current_player(state).username} starts.")
        return state

    # --------------------------------------------------------- authoritative ----
    def apply(self, state: GameState, player_id: str, action: dict[str, Any]) -> list[GameEvent]:
        if state.phase == "GAME_OVER":
            raise RuleError("game is over")
        player = self._player(state, player_id)
        kind = str(action.get("type", "")).upper()
        if player.bankrupt or player.forfeited:
            raise RuleError("inactive player")

        if kind in {"ROLL_DICE", "UPGRADE_PROPERTY", "SELL_PROPERTY", "END_TURN", "PAY_JAIL_FINE", "STAY_IN_JAIL", "BUY_PROPERTY", "SKIP_PROPERTY", "CHOOSE_LOST_PROPERTY", "LIST_AUCTION_PROPERTY", "WITHDRAW_AUCTION_LISTING", "OPT_OUT_AUCTION"} | self.AUCTION_ACTION_TYPES:
            self._check_turn_or_auction(state, player_id, kind)

        before_ids = [id(e) for e in state.events]
        before_len = len(state.events)
        if kind == "ROLL_DICE": self._roll(state, player)
        elif kind == "BUY_PROPERTY": self._buy(state, player, action.get("propertyId"))
        elif kind == "SKIP_PROPERTY": self._skip_property(state, player, action.get("propertyId"))
        elif kind == "UPGRADE_PROPERTY": self._upgrade(state, player, action.get("propertyId"))
        elif kind == "SELL_PROPERTY": self._sell(state, player, action.get("propertyId"))
        elif kind == "PAY_JAIL_FINE": self._pay_jail(state, player)
        elif kind == "STAY_IN_JAIL": self._stay_jail(state, player)
        elif kind == "CHOOSE_LOST_PROPERTY": self._choose_lost_property(state, player, action.get("propertyId"))
        elif kind == "LIST_AUCTION_PROPERTY": self._start_auction(state, player, action.get("propertyId"))
        elif kind == "START_AUCTION": self._start_auction(state, player, action.get("propertyId"))
        elif kind == "SUBMIT_AUCTION_OFFER": self._submit_auction_offer(state, player, action.get("propertyId"), action.get("listingId"), action.get("cash"))
        elif kind == "ACCEPT_AUCTION": self._accept_auction(state, player, action.get("playerId"), action.get("listingId"))
        elif kind == "WITHDRAW_AUCTION_LISTING": self._withdraw_auction_listing(state, player, action.get("listingId"))
        elif kind == "OPT_OUT_AUCTION": self._opt_out_auction(state, player)
        elif kind == "CANCEL_AUCTION": self._cancel_auction(state, player)
        elif kind == "END_TURN": self._end_turn(state, player)
        else: raise RuleError(f"unknown action: {kind}")
        self.check_all(state)
        # _emit() trims state.events to the last 100 entries; recover the new events
        # by object identity so callers still receive exactly what this action produced.
        surviving = {id(e) for e in state.events}
        emitted = [e for e in state.events if id(e) not in set(before_ids)]
        if not emitted and len(state.events) < before_len:
            return []  # nothing new survived trimming
        return emitted

    def validate_action(self, state: GameState, player_id: str, action: dict[str, Any]) -> None:
        """Best-effort precheck for transports: same guards as apply(), without mutating.

        Raises RuleError for unknown actions, non-string player references, or actions
        that are provably illegal in the current phase/turn. Used by app.py to reject
        obviously invalid payloads before touching authoritative state; apply() remains
        the final authority.
        """
        kind = str(action.get("type", "")).upper() if isinstance(action, dict) else ""
        if kind not in {"ROLL_DICE", "BUY_PROPERTY", "SKIP_PROPERTY", "UPGRADE_PROPERTY", "SELL_PROPERTY", "PAY_JAIL_FINE", "STAY_IN_JAIL", "CHOOSE_LOST_PROPERTY", "START_AUCTION", "SUBMIT_AUCTION_OFFER", "ACCEPT_AUCTION", "CANCEL_AUCTION", "END_TURN"}:
            raise RuleError("unsupported action")
        player = self._player(state, player_id)
        if player.bankrupt or player.forfeited:
            raise RuleError("inactive player")
        for field in ("propertyId", "playerId"):
            value = action.get(field)
            if value is not None and not isinstance(value, str):
                raise RuleError(f"{field} must be a string")
        if kind in {"BUY_PROPERTY", "SKIP_PROPERTY", "UPGRADE_PROPERTY", "SELL_PROPERTY", "CHOOSE_LOST_PROPERTY", "START_AUCTION", "SUBMIT_AUCTION_OFFER"} and not action.get("propertyId"):
            raise RuleError("propertyId required")
        if kind == "SUBMIT_AUCTION_OFFER":
            return
        if kind in {"ACCEPT_AUCTION", "CANCEL_AUCTION", "LIST_AUCTION_PROPERTY", "WITHDRAW_AUCTION_LISTING", "OPT_OUT_AUCTION"} and state.auction:
            self._require_current(state, player_id)
            return
        if state.phase != "PLAYING":
            raise RuleError("game is not playing")
        self._require_current(state, player_id)
        phase_guards: dict[str, set[str]] = {
            "ROLL_DICE": {"PROPERTY_MANAGEMENT", "READY_TO_ROLL"},
            "BUY_PROPERTY": {"PROPERTY_DECISION"},
            "SKIP_PROPERTY": {"PROPERTY_DECISION"},
            "UPGRADE_PROPERTY": {"PROPERTY_MANAGEMENT", "READY_TO_ROLL", "TURN_END"},
            "SELL_PROPERTY": {"PROPERTY_MANAGEMENT", "READY_TO_ROLL", "TURN_END"},
            "PAY_JAIL_FINE": {"JAILED_DECISION"},
            "STAY_IN_JAIL": {"JAILED_DECISION"},
            "CHOOSE_LOST_PROPERTY": {"CARD_DECISION"},
            "START_AUCTION": {"AUCTION"},
            "LIST_AUCTION_PROPERTY": {"AUCTION"},
            "ACCEPT_AUCTION": {"AUCTION"},
            "CANCEL_AUCTION": {"AUCTION"},
            "END_TURN": {"TURN_END"},
        }
        self._require_phase(state, *phase_guards[kind])

    # -------------------------------------------------------------- economy ----
    def calculate_net_worth(self, state: GameState, player_id: str) -> int:
        player = self._player(state, player_id)
        return player.cash + sum(state.properties[pid].purchase_price + state.properties[pid].building_level * state.properties[pid].building_price for pid in player.properties_owned)

    def owns_complete_color_set(self, state: GameState, player_id: str, color_group: str) -> bool:
        required = self._color_groups.get(color_group, [])
        return bool(required) and all(state.properties[pid].owner_id == player_id for pid in required)

    def calculate_public_property_rent(self, state: GameState, owner_id: str, property_id: str) -> int:
        p = state.properties[property_id]
        count = sum(1 for owned in self._player(state, owner_id).properties_owned if state.properties[owned].kind == "public")
        if p.rent_by_owned_count:
            return p.rent_by_owned_count[min(max(1, count), len(p.rent_by_owned_count)) - 1]
        return p.base_rent * max(1, count)

    def calculate_rent(self, state: GameState, owner_id: str, property_id: str) -> int:
        p = state.properties[property_id]
        if p.kind == "public": return self.calculate_public_property_rent(state, owner_id, property_id)
        if p.kind != "city": return 0
        group = self._color_groups.get(p.color_group or "", [])
        count = sum(1 for pid in group if state.properties[pid].owner_id == owner_id)
        if p.building_level > 0:
            return p.rent_building[p.building_level - 1]
        if group and count == len(group):
            return p.rent_with_set
        if count >= 2:
            return p.rent_owned_2
        return p.base_rent

    def sale_value(self, state: GameState, property_id: str) -> int:
        return int(state.properties[property_id].purchase_price * float(self.balance["propertySellPercentage"]))

    # -------------------------------------------------------------- actions ----
    def _roll(self, state: GameState, player: PlayerState) -> None:
        self._require_current(state, player.id)
        self._require_phase(state, "PROPERTY_MANAGEMENT", "READY_TO_ROLL")
        if state.pending_property_id or state.pending_card or state.auction:
            raise RuleError("resolve the pending decision first")
        if player.jail_turns_remaining:
            raise RuleError("choose stay or pay jail fine")
        die = self.rng.randint(1, 6)
        old_index = player.board_position
        path = []
        for step in range(1, die + 1): path.append((old_index + step) % len(state.board_ids))
        player.board_position = path[-1]
        state.last_roll, state.last_path = die, path
        state.last_roll_actor_id = player.id
        state.roll_sequence += 1
        start_index = next((i for i, raw in enumerate(self.board_data) if raw.get("kind") == "start"), 0)
        crossed = start_index in path
        self._emit(state, "DICE_ROLLED", player.id, amount=die, metadata={"path": path}, text=f"{player.username} rolled {die}.")
        if crossed:
            self._money(state, player, int(self.balance["startSalary"]))
            self._emit(state, "SALARY_RECEIVED", player.id, amount=int(self.balance["startSalary"]), text=f"{player.username} receives salary.")
            if self.calculate_net_worth(state, player.id) >= state.target_worth:
                self._finish(state, player, f"Reached ${state.target_worth} net worth first.")
                return
        self._emit(state, "PLAYER_MOVED", player.id, metadata={"path": path}, text=f"{player.username} moved to {self._property_at_player(state, player.id)}.")
        self._resolve_landing(state, player)

    def _resolve_landing(self, state: GameState, player: PlayerState) -> None:
        pid = self._property_at_player(state, player.id)
        p = state.properties[pid]
        if p.kind in {"city", "public"}:
            if p.owner_id is None:
                state.pending_property_id = pid; state.turn_phase = "PROPERTY_DECISION"
                self._emit(state, "PROPERTY_DECISION", player.id, property_id=pid, text=f"{player.username} may buy {p.name}.")
            elif p.owner_id != player.id:
                rent = self.calculate_rent(state, p.owner_id, pid)
                visitor = player; owner = self._player(state, p.owner_id)
                self._money(state, visitor, -rent); self._money(state, owner, rent)
                self._emit(state, "RENT_PAID", visitor.id, target_id=owner.id, amount=rent, property_id=pid, text=f"{visitor.username} paid ${rent} rent to {owner.username}.")
                self._after_landing(state, player)
            else: self._after_landing(state, player)
        elif p.kind == "lucky":
            self._draw_lucky(state, player)
            if state.phase != "GAME_OVER" and self.current_player(state).id == player.id:
                self._after_landing(state, player)
        elif p.kind == "jail": player.jail_turns_remaining = int(self.balance["jailTurns"]); self._emit(state, "PLAYER_JAILED", player.id, text=f"{player.username} is in Jail."); self._after_landing(state, player)
        elif p.kind == "goto_jail":
            jail = next(x for x in self.board_data if x["kind"] == "jail"); player.board_position = state.board_ids.index(jail["id"]); player.jail_turns_remaining = int(self.balance["jailTurns"]); self._emit(state, "PLAYER_JAILED", player.id, text=f"{player.username} goes to Jail."); self._after_landing(state, player)
        elif p.kind == "auction": state.auction = AuctionState(initiator_id=player.id); state.turn_phase = "AUCTION"; self._emit(state, "AUCTION_STARTED", player.id, text=f"{player.username} can start an Auction.")
        else: self._after_landing(state, player)

    def _after_landing(self, state: GameState, player: PlayerState) -> None:
        if state.pending_property_id or state.pending_card or state.auction:
            return
        if player.jail_turns_remaining:
            state.extra_roll = False
            state.turn_phase = "JAILED_DECISION"
            return
        state.extra_roll = bool(state.last_roll == 6 and self.balance.get("bonusRollOnSix", True))
        if state.extra_roll:
            state.turn_phase = "READY_TO_ROLL"
        else:
            self._end_turn(state, player, automatic=True)

    def _buy(self, state: GameState, player: PlayerState, property_id: str | None) -> None:
        self._require_current(state, player.id); self._require_phase(state, "PROPERTY_DECISION")
        if not isinstance(property_id, str) or property_id != state.pending_property_id: raise RuleError("not the landed property")
        p = state.properties[property_id]
        if p.owner_id is not None: raise RuleError("already owned")
        if player.cash < p.purchase_price: raise RuleError("not enough cash")
        self._money(state, player, -p.purchase_price); p.owner_id = player.id; player.properties_owned.add(p.id); state.pending_property_id = None
        self._emit(state, "PROPERTY_BOUGHT", player.id, amount=p.purchase_price, property_id=p.id, text=f"{player.username} bought {p.name}.")
        if p.color_group and self.owns_complete_color_set(state, player.id, p.color_group): self._emit(state, "COLOR_SET_COMPLETED", player.id, property_id=p.id, metadata={"colorGroup": p.color_group}, text=f"{player.username} completed {p.color_group}.")
        self._after_landing(state, player)

    def _skip_property(self, state: GameState, player: PlayerState, property_id: str | None) -> None:
        self._require_current(state, player.id); self._require_phase(state, "PROPERTY_DECISION")
        if not isinstance(property_id, str) or property_id != state.pending_property_id: raise RuleError("not the landed property")
        state.pending_property_id = None; self._emit(state, "PROPERTY_SKIPPED", player.id, property_id=property_id, text=f"{player.username} skipped the property."); self._after_landing(state, player)

    def _upgrade(self, state: GameState, player: PlayerState, property_id: str | None) -> None:
        self._require_current(state, player.id); self._require_phase(state, "PROPERTY_MANAGEMENT", "READY_TO_ROLL", "TURN_END")
        if not isinstance(property_id, str) or not property_id or property_id not in player.properties_owned: raise RuleError("you do not own that city")
        p = state.properties[property_id]
        if p.kind != "city" or not self.owns_complete_color_set(state, player.id, p.color_group or ""): raise RuleError("complete the color set first")
        if p.building_level >= int(self.balance["maxBuildingsPerCity"]): raise RuleError("maximum buildings reached")
        if player.cash < p.building_price: raise RuleError("not enough cash")
        self._money(state, player, -p.building_price); p.building_level += 1; self._emit(state, "BUILDING_PURCHASED", player.id, amount=p.building_price, property_id=p.id, metadata={"level": p.building_level}, text=f"{player.username} upgraded {p.name} to level {p.building_level}.")

    def _sell(self, state: GameState, player: PlayerState, property_id: str | None) -> None:
        self._require_current(state, player.id); self._require_phase(state, "PROPERTY_MANAGEMENT", "READY_TO_ROLL", "TURN_END")
        if not isinstance(property_id, str) or not property_id or property_id not in player.properties_owned: raise RuleError("you do not own that")
        p = state.properties[property_id]; value = self.sale_value(state, property_id); owner = player.id
        player.properties_owned.remove(property_id); p.owner_id = None; p.building_level = 0; self._money(state, player, value); self._emit(state, "PROPERTY_SOLD", owner, amount=value, property_id=property_id, text=f"{player.username} sold {p.name} for ${value}.")

    def _pay_jail(self, state: GameState, player: PlayerState) -> None:
        self._require_current(state, player.id); self._require_phase(state, "JAILED_DECISION")
        fine = int(self.balance["jailFine"])
        if player.cash < fine: raise RuleError("not enough cash")
        self._money(state, player, -fine); player.jail_turns_remaining = 0; state.turn_phase = "PROPERTY_MANAGEMENT"; self._emit(state, "JAIL_FINE_PAID", player.id, amount=fine, text=f"{player.username} paid bail.")

    def _stay_jail(self, state: GameState, player: PlayerState) -> None:
        self._require_current(state, player.id); self._require_phase(state, "JAILED_DECISION")
        player.jail_turns_remaining -= 1; self._emit(state, "JAIL_TURN_USED", player.id, text=f"{player.username} stays in Jail.")
        if player.jail_turns_remaining <= 0: player.jail_turns_remaining = 0
        self._end_turn(state, player, automatic=True)

    def _choose_lost_property(self, state: GameState, player: PlayerState, property_id: str | None) -> None:
        self._require_current(state, player.id)
        if not state.pending_card or state.pending_card.get("effectType") != "choose_lose_property": raise RuleError("no property choice pending")
        if not isinstance(property_id, str) or property_id not in player.properties_owned: raise RuleError("you do not own that")
        p = state.properties[property_id]; player.properties_owned.remove(property_id); p.owner_id = None; p.building_level = 0; state.pending_card = None; self._emit(state, "PROPERTY_LOST", player.id, property_id=property_id, text=f"{player.username} lost {p.name}."); self._after_landing(state, player)

    # --------------------------------------------------------------- lucky -----
    def _draw_lucky(self, state: GameState, player: PlayerState) -> None:
        weights = [int(c.get("weight", 1)) for c in self.card_data]
        card = self.rng.choices(self.card_data, weights=weights, k=1)[0]
        self._emit(state, "LUCKY_CARD_DRAWN", player.id, metadata={"card": card}, text=f"? {card['title']}: {card['description']}")
        effect = card["effectType"]; value = int(card.get("value", 0))
        if effect == "choose_lose_property":
            if player.properties_owned:
                state.pending_card = card; state.turn_phase = "CARD_DECISION"; return
            self._emit(state, "CARD_NO_EFFECT", player.id, text=f"{player.username} owns no property to lose.")
            return
        if effect == "lose_cheapest_property" and player.properties_owned:
            pid = min(player.properties_owned, key=lambda x: state.properties[x].purchase_price); self._remove_property(state, player, pid); self._emit(state, "PROPERTY_LOST", player.id, property_id=pid, text=f"{player.username} lost a property to foreclosure.")
        elif effect == "pay_per_building": self._money(state, player, -value * sum(state.properties[x].building_level for x in player.properties_owned))
        elif effect == "receive_per_city": self._money(state, player, value * sum(state.properties[x].kind == "city" for x in player.properties_owned))
        elif effect == "receive_cash": self._money(state, player, value)
        elif effect == "pay_cash": self._money(state, player, -value)
        elif effect == "pay_per_property": self._money(state, player, -value * len(player.properties_owned))
        elif effect == "move_to_start":
            player.board_position = next((i for i, raw in enumerate(self.board_data) if raw.get("kind") == "start"), 0)
            self._money(state, player, int(self.balance["startSalary"]))
            self._emit(state, "SALARY_RECEIVED", player.id, amount=int(self.balance["startSalary"]), text=f"{player.username} receives salary.")
            if self.calculate_net_worth(state, player.id) >= state.target_worth:
                self._finish(state, player, f"Reached ${state.target_worth} net worth first.")
                return
        elif effect == "move_relative":
            old_position = player.board_position
            path = [(old_position + step) % len(state.board_ids) for step in range(1, value + 1)]
            player.board_position = path[-1]
            start_index = next((i for i, raw in enumerate(self.board_data) if raw.get("kind") == "start"), 0)
            if start_index in path:
                salary = int(self.balance["startSalary"])
                self._money(state, player, salary)
                self._emit(state, "SALARY_RECEIVED", player.id, amount=salary, text=f"{player.username} receives salary.")
                if self.calculate_net_worth(state, player.id) >= state.target_worth:
                    self._finish(state, player, f"Reached ${state.target_worth} net worth first.")
                    return
            self._emit(state, "PLAYER_MOVED", player.id, metadata={"path": path, "source": "card"}, text=f"{player.username} advances {value} spaces.")
            landed = self.board_data[player.board_position]
            if landed["kind"] == "lucky":
                self._emit(state, "PLAYER_MOVED", player.id, text=f"{player.username} moved to {landed['name']}.")
            else:
                self._resolve_landing(state, player)
        elif effect == "go_to_jail":
            jail_id = next(x["id"] for x in self.board_data if x["kind"] == "jail"); player.board_position = state.board_ids.index(jail_id); player.jail_turns_remaining = int(self.balance["jailTurns"])
            self._emit(state, "PLAYER_JAILED", player.id, text=f"{player.username} goes directly to Jail.")
        elif effect == "gift_property":
            free = [p for p in state.properties.values() if p.kind in {"city", "public"} and p.owner_id is None]
            if free:
                p = self.rng.choice(free); p.owner_id = player.id; player.properties_owned.add(p.id); self._emit(state, "PROPERTY_GIFTED", player.id, property_id=p.id, text=f"{player.username} received {p.name}.")
            else: self._money(state, player, 100); self._emit(state, "CASH_RECEIVED", player.id, amount=100, text=f"No property left to gift — {player.username} collects $100 instead.")

    # --------------------------------------------------------------- auction ----
    AUCTION_ACTION_TYPES = {"LIST_AUCTION_PROPERTY", "SUBMIT_AUCTION_OFFER", "ACCEPT_AUCTION", "WITHDRAW_AUCTION_LISTING", "OPT_OUT_AUCTION", "CANCEL_AUCTION"}

    def _auction_or_fail(self, state: GameState) -> AuctionState:
        if not state.auction: raise RuleError("no auction in progress")
        return state.auction

    def _listing_for(self, a: AuctionState, listing_id: str | None) -> AuctionListing:
        for l in a.listings:
            if l.id == listing_id: return l
        raise RuleError("listing not found")

    def _start_auction(self, state: GameState, player: PlayerState, property_id: str | None, cash: int | None = None) -> None:
        """List one of your own properties on the auction board (legacy LIST alias)."""
        self._require_phase(state, "AUCTION")
        a = self._auction_or_fail(state)
        if not isinstance(property_id, str) or property_id not in player.properties_owned: raise RuleError("choose your property")
        if any(l.property_id == property_id for l in a.listings): raise RuleError("already listed")
        if len(a.listings) >= 4: raise RuleError("auction board is full")
        a.listings.append(AuctionListing(seller_id=player.id, property_id=property_id))
        a.quiet_cycles = 0
        self._emit(state, "AUCTION_PROPERTY_SELECTED", player.id, property_id=property_id, text=f"{player.username} listed {state.properties[property_id].name} on the auction board.")

    def _submit_auction_offer(self, state: GameState, player: PlayerState, property_id: str | None, listing_id: str | None = None, cash: int | None = None) -> None:
        """Bid on any listing with a property and/or cash. Anyone may bid, including the seller topping up."""
        self._require_phase(state, "AUCTION")
        a = self._auction_or_fail(state)
        if not a.listings:
            # Legacy single-property flow: the first offer implicitly lists whatever the
            # turn holder's auction landing was (their current board space, if tradable).
            if not isinstance(property_id, str) or property_id not in player.properties_owned: raise RuleError("choose a property you own")
            current = self.current_player(state)
            landed = self._property_at_player(state, current.id)
            if state.properties[landed].kind not in {"city", "public"}:
                raise RuleError("no property is listed for auction yet")
            a.listings.append(AuctionListing(seller_id=current.id, property_id=landed))
            self._emit(state, "AUCTION_PROPERTY_SELECTED", current.id, property_id=landed, text=f"Auction board opened for {state.properties[landed].name}.")
        target_listing = self._listing_for(a, listing_id) if listing_id else a.listings[0]
        has_prop = isinstance(property_id, str) and bool(property_id)
        if not has_prop and not cash: raise RuleError("offer needs a property or cash")
        if has_prop and property_id not in player.properties_owned: raise RuleError("you do not own that property")
        if has_prop and any(l.property_id == property_id for l in a.listings): raise RuleError("that property is already listed")
        if cash is not None:
            if not isinstance(cash, int) or isinstance(cash, bool): raise RuleError("cash must be a whole amount")
            if cash <= 0: raise RuleError("cash offer must be positive")
            if cash > player.cash: raise RuleError("not enough cash")
        prop_value = state.properties[target_listing.property_id].purchase_price
        offered_value = 0
        if has_prop:
            op = state.properties[property_id]; offered_value += op.purchase_price
        offered_value += int(cash or 0)
        if player.id != target_listing.seller_id and offered_value < prop_value and not cash:
            # Pure lowball property bids are allowed only when the bidder adds no cash and
            # the property is within 40% of value — keeps offers meaningful without hard blocks.
            if offered_value < int(prop_value * 0.4):
                raise RuleError("offer too far below the asking property's value")
        bid = dict(target_listing.bids.get(player.id, {}))
        if has_prop:
            prev = bid.get("propertyId")
            if prev and prev != property_id and state.properties[prev].purchase_price > op.purchase_price:
                raise RuleError("your existing bid includes a better property — withdraw it first")
            bid["propertyId"] = property_id
        if cash: bid["cash"] = int(cash)
        target_listing.bids[player.id] = bid
        a.quiet_cycles = 0
        parts = []
        if has_prop: parts.append(state.properties[property_id].name)
        if cash: parts.append(f"${cash}")
        self._emit(state, "AUCTION_OFFERED", player.id, property_id=target_listing.property_id, metadata={"listingId": target_listing.id}, text=f"{player.username} bids {' + '.join(parts)} for {state.properties[target_listing.property_id].name}.")

    def _withdraw_auction_listing(self, state: GameState, player: PlayerState, listing_id: str | None) -> None:
        """Seller pulls their own listing off the board."""
        self._require_phase(state, "AUCTION")
        a = self._auction_or_fail(state)
        listing = self._listing_for(a, listing_id)
        if listing.seller_id != player.id: raise RuleError("not your listing")
        a.listings.remove(listing); listing.bids.clear()
        self._emit(state, "AUCTION_LISTING_WITHDRAWN", player.id, property_id=listing.property_id, text=f"{player.username} withdrew {state.properties[listing.property_id].name} from the auction.")
        if not a.listings: self._cancel_auction(state, player)

    def _accept_auction(self, state: GameState, player: PlayerState, player_id: str | None, listing_id: str | None = None) -> None:
        """Seller accepts a bid on one of their listings; settlement swaps property and moves cash."""
        self._require_phase(state, "AUCTION")
        a = self._auction_or_fail(state)
        if a.listings:
            listing = self._listing_for(a, listing_id) if listing_id else a.listings[0]
            if listing.seller_id != player.id: raise RuleError("only the seller can accept this offer")
        else:
            raise RuleError("no listing to accept")
        bidder_id = str(player_id) if isinstance(player_id, str) and player_id else None
        if not bidder_id or bidder_id == player.id or bidder_id not in listing.bids: raise RuleError("bid not found")
        bid = dict(listing.bids[bidder_id])
        giver = self._player(state, bidder_id)
        offered_prop = state.properties[listing.property_id]
        # Settlement: the listed property changes hands first, then the bid settles.
        self._swap_single(state, listing.property_id, from_player=player, to_player=giver)
        bonus = int(self.balance["successfulAuctionBonus"])
        if bid.get("propertyId"):
            self._swap_single(state, bid["propertyId"], from_player=giver, to_player=player)
        if bid.get("cash"):
            # Cash offers are promises settled at accept time; cap at what the bidder
            # still holds so a mid-auction rent hit can't push anyone through the floor.
            payable = min(int(bid["cash"]), max(giver.cash, 0))
            if payable > 0:
                self._money(state, giver, -payable); self._money(state, player, payable)
                bid["cash"] = payable
            else:
                bid["cash"] = 0
        self._money(state, player, bonus); self._money(state, giver, bonus)
        self._emit(state, "TRADE_COMPLETED", player.id, target_id=giver.id, amount=bonus, metadata={"listingId": listing.id, "soldProperty": listing.property_id, "receivedProperty": bid.get("propertyId"), "receivedCash": int(bid.get("cash", 0))},
                   text=f"Deal! {giver.username} gets {offered_prop.name}" + (f" + ${bid['cash']}" if bid.get('cash') else "") + (f" for {state.properties[bid['propertyId']].name}" if bid.get("propertyId") else f" for ${bid['cash']}") + ".")
        a.listings.remove(listing)
        for other in list(a.listings):
            other.bids.pop(bidder_id, None)
        if not a.listings:
            state.auction = None
            current = self.current_player(state)
            if current.id == player.id:
                self._after_landing(state, player)  # normal flow: seller was the turn holder
            elif state.turn_phase == "AUCTION":
                # Seller was not the turn holder (portal deal during someone else's turn):
                # hand control back to the turn holder so play resumes.
                if current.jail_turns_remaining:
                    state.extra_roll = False; state.turn_phase = "JAILED_DECISION"
                else:
                    state.extra_roll = bool(state.last_roll == 6 and self.balance.get("bonusRollOnSix", True))
                    state.turn_phase = "READY_TO_ROLL" if state.extra_roll else "PROPERTY_MANAGEMENT"

    def _opt_out_auction(self, state: GameState, player: PlayerState) -> None:
        """Anyone may sit an auction out; they keep their properties and take no further part."""
        self._require_phase(state, "AUCTION")
        a = self._auction_or_fail(state)
        if player.id in a.opted_out: return
        a.opted_out.add(player.id)
        for listing in a.listings: listing.bids.pop(player.id, None)
        self._emit(state, "AUCTION_OPTED_OUT", player.id, text=f"{player.username} sits out of the Auction.")

    def _cancel_auction(self, state: GameState, player: PlayerState) -> None:
        self._require_phase(state, "AUCTION")
        a = self._auction_or_fail(state)
        current = self.current_player(state)
        is_initiator = player.id == a.initiator_id
        is_turn_holder = player.id == current.id
        others = [p for p in state.players.values() if p.id != a.initiator_id and not p.bankrupt and not p.forfeited]
        everyone_else_out = bool(others) and all(p.id in a.opted_out for p in others)
        if not (is_initiator or is_turn_holder or everyone_else_out): raise RuleError("only the initiator can cancel")
        state.auction = None
        self._emit(state, "AUCTION_CANCELLED", player.id, text=f"The Auction was called off.")
        if is_turn_holder: self._after_landing(state, current)

    def _swap_single(self, state: GameState, property_id: str, from_player: PlayerState, to_player: PlayerState) -> None:
        p = state.properties[property_id]
        if p.owner_id != from_player.id: raise RuleError("seller no longer owns that property")
        from_player.properties_owned.discard(property_id); to_player.properties_owned.add(property_id); p.owner_id = to_player.id

    def _resolve_stale_auction(self, state: GameState) -> None:
        """Watchdog: close the auction when every non-initiator has passed or gone quiet."""
        a = state.auction
        if not a: return
        current = self.current_player(state)
        others = [p for p in state.players.values() if p.id != a.initiator_id and not p.bankrupt and not p.forfeited]
        everyone_out = all(p.id in a.opted_out for p in others)
        nothing_listed = not a.listings
        no_external_bids = all(
            all(bidder == l.seller_id for bidder in l.bids) or not l.bids
            for l in a.listings)
        if (everyone_out or nothing_listed or (no_external_bids and all(l.seller_id in a.opted_out or self._player(state, l.seller_id).is_bot for l in a.listings))) :
            a.quiet_cycles += 1
            if a.quiet_cycles >= 3:
                self._emit(state, "AUCTION_CANCELLED", current.id, text="Everyone passed — Auction closed.")
                state.auction = None; self._after_landing(state, current)

    # --------------------------------------------------------------- turn ------
    def _end_turn(self, state: GameState, player: PlayerState, automatic: bool = False) -> None:
        self._require_current(state, player.id)
        if not automatic:
            self._require_phase(state, "TURN_END")
        if state.pending_property_id or state.pending_card or state.auction: raise RuleError("resolve pending decision first")
        active = self._active_order(state)
        if not active: return
        old_round = state.current_round; current_pos = active.index(player.id)
        next_id = active[(current_pos + 1) % len(active)]
        if current_pos + 1 >= len(active):
            if state.round_limit and state.current_round >= state.round_limit:
                self._finish_by_rank(state)
                return
            state.current_round += 1
        state.turn_order = active; state.turn_index = active.index(next_id); state.turn_phase = "JAILED_DECISION" if self._player(state, next_id).jail_turns_remaining else "PROPERTY_MANAGEMENT"; state.extra_roll = False
        self._emit(state, "TURN_STARTED", next_id, text=f"{self._player(state, next_id).username}'s turn.")

    def _pass_round_wrap(self, state: GameState, eliminated_id: str, order: list[str]) -> bool:
        """True when eliminating a player skipped the seat that would have closed the round."""
        if eliminated_id not in order:
            return False
        return order.index(eliminated_id) == len(order) - 1

    # --------------------------------------------------------------- victory ----
    def check_all(self, state: GameState) -> None:
        old_order = list(state.turn_order)
        old_index = state.turn_index
        old_current = old_order[old_index] if old_order and 0 <= old_index < len(old_order) else None
        # Eliminated players lose their properties first so they cannot win by rank
        # or keep collecting rent with a dead seat.
        for p in list(state.players.values()): self.check_bankruptcy(state, p.id)
        if state.phase == "GAME_OVER": return
        active = self._active_players(state)
        active_ids = {p.id for p in active}
        if old_order and (old_current not in active_ids or any(pid not in active_ids for pid in old_order)):
            new_order = [pid for pid in old_order if pid in active_ids]
            new_order.extend(p.id for p in active if p.id not in new_order)
            if new_order:
                if old_current in active_ids:
                    next_id = old_current
                else:
                    next_id = next((old_order[(old_index + step) % len(old_order)] for step in range(1, len(old_order) + 1) if old_order[(old_index + step) % len(old_order)] in active_ids), new_order[0])
                state.turn_order = new_order
                state.turn_index = new_order.index(next_id)
                if old_current not in active_ids:
                    nxt = self._player(state, next_id)
                    state.turn_phase = "JAILED_DECISION" if nxt.jail_turns_remaining else "PROPERTY_MANAGEMENT"
                    state.extra_roll = False
                    # If the eliminated player was the final seat, their removal
                    # closed the round: wrap now so round caps trigger on time.
                    if self._pass_round_wrap(state, old_current, old_order):
                        if state.round_limit and state.current_round >= state.round_limit:
                            self._finish_by_rank(state)
                            return
                        state.current_round += 1
                    if len(active) > 1:
                        self._emit(state, "TURN_STARTED", nxt.id, text=f"{nxt.username}'s turn after bankruptcy.")
        rich = [p for p in active if self.calculate_net_worth(state, p.id) >= state.target_worth]
        if rich:
            winner = max(rich, key=lambda p: (self.calculate_net_worth(state, p.id), p.cash, self._property_value(state, p.id)))
            self._finish(state, winner, f"Reached ${state.target_worth} net worth first.")
        elif len(active) == 1:
            self._finish(state, active[0], "Last active player standing.")

    def forfeit(self, state: GameState, player_id: str) -> None:
        """Remove a player permanently (e.g. abandoned seat) and return assets to the bank."""
        player = self._player(state, player_id)
        if player.forfeited or player.bankrupt: return
        player.forfeited = True
        for pid in list(player.properties_owned): self._remove_property(state, player, pid)
        if state.phase != "GAME_OVER":
            self._emit(state, "PLAYER_FORFEITED", player_id, text=f"{player.username} left the game.")
            self.check_all(state)


    def check_bankruptcy(self, state: GameState, player_id: str) -> bool:
        p = self._player(state, player_id)
        if p.bankrupt or p.forfeited: return True
        if p.cash <= int(self.balance["bankruptcyCashFloor"]) or self.calculate_net_worth(state, player_id) <= 0:
            p.bankrupt = True
            for pid in list(p.properties_owned): self._remove_property(state, p, pid)
            self._emit(state, "PLAYER_BANKRUPT", player_id, text=f"{p.username} went bankrupt.")
            return True
        return False

    def check_bankruptcy_before_rank(self, state: GameState) -> None:
        """Bankruptcy must be resolved before any rank-based finish so an eliminated
        player is never chosen as the round-cap winner."""
        for p in list(state.players.values()):
            self.check_bankruptcy(state, p.id)

    # --------------------------------------------------------------- helpers ----
    def current_player(self, state: GameState) -> PlayerState: return self._player(state, state.turn_order[state.turn_index])
    def _active_players(self, state: GameState) -> list[PlayerState]: return [p for p in state.players.values() if not p.bankrupt and not p.forfeited]
    def _active_order(self, state: GameState) -> list[str]: return [pid for pid in state.turn_order if pid in {p.id for p in self._active_players(state)}]
    def _player(self, state: GameState, pid: str | None) -> PlayerState:
        if not pid or pid not in state.players: raise RuleError("unknown player")
        return state.players[pid]
    def _require_current(self, state: GameState, pid: str) -> None:
        if self.current_player(state).id != pid: raise RuleError("not your turn")
    def _require_phase(self, state: GameState, *phases: str) -> None:
        if state.turn_phase not in phases: raise RuleError(f"illegal in phase {state.turn_phase}")
    def _check_turn_or_auction(self, state: GameState, pid: str, kind: str) -> None:
        if kind in {"SUBMIT_AUCTION_OFFER", "OPT_OUT_AUCTION", "WITHDRAW_AUCTION_LISTING"}:
            return
        if kind == "ACCEPT_AUCTION" and state.auction:
            listing = next((l for l in state.auction.listings if l.seller_id == pid), None)
            if listing is not None: return  # any seller accepts bids on their own listing
            self._require_current(state, pid); return
        if kind in {"START_AUCTION", "LIST_AUCTION_PROPERTY"}:
            self._require_phase(state, "AUCTION"); return  # anyone may list during an open auction; phase check happens in the action
        if kind == "CANCEL_AUCTION":
            a = state.auction
            if a:
                current = self.current_player(state)
                others = [p for p in state.players.values() if p.id != a.initiator_id and not p.bankrupt and not p.forfeited]
                everyone_else_out = bool(others) and all(p.id in a.opted_out for p in others)
                if pid == a.initiator_id or pid == current.id or everyone_else_out: return
            raise RuleError("only the initiator can cancel")
        self._require_current(state, pid)
    def _property_at_player(self, state: GameState, pid: str) -> str: return state.board_ids[self._player(state, pid).board_position]
    def _money(self, state: GameState, player: PlayerState, amount: int) -> None: player.cash += amount
    def _property_value(self, state: GameState, pid: str) -> int: return sum(state.properties[x].purchase_price for x in self._player(state, pid).properties_owned)
    def _remove_property(self, state: GameState, player: PlayerState, property_id: str) -> None:
        if property_id in player.properties_owned: player.properties_owned.remove(property_id)
        p = state.properties[property_id]; p.owner_id = None; p.building_level = 0
    def _swap_properties(self, state: GameState, a: PropertyState, b: PropertyState) -> None:
        ao, bo = a.owner_id, b.owner_id; a.owner_id, b.owner_id = bo, ao
        if ao: self._player(state, ao).properties_owned.discard(a.id); self._player(state, ao).properties_owned.add(b.id)
        if bo: self._player(state, bo).properties_owned.discard(b.id); self._player(state, bo).properties_owned.add(a.id)
    def _finish(self, state: GameState, winner: PlayerState, reason: str) -> None:
        state.phase = "GAME_OVER"; state.turn_phase = "GAME_OVER"; state.winner_id = winner.id; state.win_reason = reason; winner.wins += 1; self._emit(state, "PLAYER_WON", winner.id, text=f"{winner.username} won — {reason}")
    def _finish_by_rank(self, state: GameState) -> None:
        self.check_bankruptcy_before_rank(state)
        if state.phase == "GAME_OVER": return
        active = self._active_players(state)
        if not active:
            return
        winner = max(active, key=lambda p: (self.calculate_net_worth(state, p.id), p.cash, self._property_value(state, p.id), -state.turn_order.index(p.id) if p.id in state.turn_order else 0))
        self._finish(state, winner, f"Round {state.round_limit} cap reached; highest net worth.")
    def _emit(self, state: GameState, typ: str, actor_id: str | None = None, target_id: str | None = None, amount: int | None = None, property_id: str | None = None, metadata: dict[str, Any] | None = None, text: str = "") -> GameEvent:
        event = GameEvent(typ, actor_id, target_id, amount, property_id, metadata or {}, text); state.events.append(event); state.events = state.events[-100:]; return event

    def snapshot(self, state: GameState, viewer_id: str | None = None) -> dict[str, Any]:
        def player_json(p: PlayerState) -> dict[str, Any]:
            return {"id": p.id, "name": p.username, "username": p.username, "avatar": p.avatar, "color": p.color, "connected": p.connected, "isBot": p.is_bot, "pos": p.board_position, "cash": p.cash, "net_worth": self.calculate_net_worth(state, p.id), "jailed": p.jail_turns_remaining, "bankrupt": p.bankrupt, "forfeited": p.forfeited, "wins": p.wins, "properties": [{"tile": state.board_ids.index(pid), "id": pid, "name": state.properties[pid].name, "color": state.properties[pid].color_group, "buildings": state.properties[pid].building_level} for pid in sorted(p.properties_owned, key=lambda x: state.board_ids.index(x))]}
        def property_json(p: PropertyState) -> dict[str, Any]:
            if p.kind == "city":
                group = self._color_groups.get(p.color_group or "", [])
                owned_count = sum(1 for pid in group if p.owner_id and state.properties[pid].owner_id == p.owner_id)
                set_size = len(group)
            elif p.kind == "public":
                owned_count = sum(1 for pid in self._player(state, p.owner_id).properties_owned if state.properties[pid].kind == "public") if p.owner_id else 0
                set_size = len([x for x in state.properties.values() if x.kind == "public"])
            else:
                owned_count = set_size = 0
            current_rent = self.calculate_rent(state, p.owner_id, p.id) if p.owner_id else p.base_rent
            return {"id":p.id, "kind":p.kind, "name":p.name, "color":p.color_group, "colorGroup":p.color_group, "price":p.purchase_price, "purchasePrice":p.purchase_price, "rent":p.base_rent, "baseRent":p.base_rent, "rentOwned2":p.rent_owned_2, "rentWithSet":p.rent_with_set, "rentBuilding1":p.rent_building[0], "rentBuilding2":p.rent_building[1], "rentBuilding3":p.rent_building[2], "rentByOwnedCount":list(p.rent_by_owned_count), "currentRent":current_rent, "ownedCount":owned_count, "setSize":set_size, "buildingPrice":p.building_price, "ownerId":p.owner_id, "buildingLevel":p.building_level, "icon":p.icon}
        props = [property_json(state.properties[x]) for x in state.board_ids]
        return {"type":"state", "phase":state.phase.lower(), "enginePhase":state.turn_phase, "target_worth":state.target_worth, "round_limit":state.round_limit, "round_number":state.current_round, "current_id":self.current_player(state).id if state.turn_order else None, "current_name":self.current_player(state).username if state.turn_order else None, "last_roll":state.last_roll, "last_path":state.last_path, "last_roll_actor_id":state.last_roll_actor_id, "roll_sequence":state.roll_sequence, "pending_move":False, "pending_property":state.pending_property_id, "pending_lose":({"player_id":self.current_player(state).id} if state.pending_card else None), "winner_id":state.winner_id, "win_reason":state.win_reason, "auction":self._auction_json(state), "trade":None, "board":props, "players":[player_json(p) for p in state.players.values()], "viewer":viewer_id, "you":player_json(state.players[viewer_id]) if viewer_id in state.players else None, "log":[e.text for e in state.events[-14:] if e.text], "events":[e.__dict__ for e in state.events[-20:]]}

    def _auction_json(self, state: GameState) -> dict[str, Any] | None:
        if not state.auction: return None
        a = state.auction

        def bid_json(listing: AuctionListing, bidder: str, bid: dict[str, Any]) -> dict[str, Any]:
            prop = state.properties.get(bid.get("propertyId", "")) if bid.get("propertyId") else None
            value = int(bid.get("cash", 0)) + (prop.purchase_price if prop else 0)
            return {"playerId": bidder, "playerName": self._player(state, bidder).username,
                    "propertyId": bid.get("propertyId"), "propertyName": prop.name if prop else None,
                    "cash": int(bid.get("cash", 0)), "value": value}

        def listing_json(l: AuctionListing) -> dict[str, Any]:
            lp = state.properties[l.property_id]
            seller = self._player(state, l.seller_id)
            group_ids = self._color_groups.get(lp.color_group or "", []) if lp.kind == "city" else []
            owner_count = sum(1 for pid in group_ids if state.properties[pid].owner_id == l.seller_id) if group_ids else 0
            return {"listingId": l.id, "sellerId": l.seller_id, "sellerName": seller.username,
                    "propertyId": l.property_id, "propertyName": lp.name, "kind": lp.kind,
                    "colorGroup": lp.color_group, "price": lp.purchase_price, "currentRent": self.calculate_rent(state, l.seller_id, l.property_id),
                    "sellerSetProgress": f"{owner_count}/{len(group_ids)}" if group_ids else None,
                    "bids": [bid_json(l, b, bid) for b, bid in l.bids.items()]}

        current = self.current_player(state)
        pending = sorted(p.id for p in state.players.values()
                         if not p.bankrupt and not p.forfeited and p.id != a.initiator_id
                         and p.id not in a.opted_out and not p.is_bot)
        return {"initiatorId": a.initiator_id, "initiatorName": self._player(state, a.initiator_id).username,
                "turnHolder": current.id, "listings": [listing_json(l) for l in a.listings],
                "optedIn": [p.id for p in state.players.values() if p.id not in a.opted_out and not p.bankrupt and not p.forfeited],
                "optedOut": [{"playerId": pid, "playerName": self._player(state, pid).username} for pid in sorted(a.opted_out)],
                "waitingFor": pending}


def load_engine(seed: int | None = None) -> GameEngine:
    return GameEngine(CONFIG, seed=seed)
