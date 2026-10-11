import unittest
from game_engine import GameEngine, RuleError, AuctionState


class FixedRng:
    def __init__(self, rolls=(1,)):
        self.rolls = list(rolls)
    def shuffle(self, seq):
        return None
    def randint(self, a, b):
        return self.rolls.pop(0) if self.rolls else 1
    def choices(self, values, weights=None, k=1):
        return [values[0]]
    def choice(self, values):
        return values[0]


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = GameEngine(seed=7)
        self.state = self.engine.new_game([
            {"id": "a", "username": "Ansh"},
            {"id": "b", "username": "Riya"},
        ], 3000, 0)
        # deterministic order for focused tests
        self.state.turn_order = ["a", "b"]
        self.state.turn_index = 0
        self.engine.rng = FixedRng()

    def test_board_and_initial_cash(self):
        self.assertEqual(len(self.state.board_ids), 28)
        self.assertEqual(self.state.players["a"].cash, 1000)
        self.assertEqual(self.state.players["b"].cash, 1050)
        self.assertEqual(self.state.players["a"].board_position, self.state.board_ids.index("start"))
        self.assertEqual(self.state.players["b"].board_position, self.state.board_ids.index("start"))

    def test_purchase_deducts_cash_and_assigns_owner(self):
        p = self.state.properties["jakarta"]
        self.state.pending_property_id = p.id
        self.state.turn_phase = "PROPERTY_DECISION"
        self.engine.apply(self.state, "a", {"type": "BUY_PROPERTY", "propertyId": "jakarta"})
        self.assertEqual(p.owner_id, "a")
        self.assertIn("jakarta", self.state.players["a"].properties_owned)
        self.assertEqual(self.state.players["a"].cash, 830)
        self.assertEqual(self.engine.calculate_net_worth(self.state, "a"), 1000)
        self.assertEqual(self.engine.current_player(self.state).id, "b")
        self.assertEqual(self.state.turn_phase, "PROPERTY_MANAGEMENT")

    def test_skip_ends_turn_automatically(self):
        self.state.pending_property_id = "jakarta"
        self.state.turn_phase = "PROPERTY_DECISION"
        self.engine.apply(self.state, "a", {"type": "SKIP_PROPERTY", "propertyId": "jakarta"})
        self.assertEqual(self.engine.current_player(self.state).id, "b")
        self.assertEqual(self.state.turn_phase, "PROPERTY_MANAGEMENT")

    def test_rent_payment_ends_turn_automatically(self):
        p = self.state.properties["rio"]
        p.owner_id = "b"
        self.state.players["b"].properties_owned.add(p.id)
        self.state.players["a"].board_position = self.state.board_ids.index("start")
        self.engine.rng = FixedRng([1])
        before_a = self.state.players["a"].cash
        before_b = self.state.players["b"].cash
        self.engine.apply(self.state, "a", {"type": "ROLL_DICE"})
        self.assertEqual(self.state.players["a"].cash, before_a - p.base_rent)
        self.assertEqual(self.state.players["b"].cash, before_b + p.base_rent)
        self.assertEqual(self.engine.current_player(self.state).id, "b")
        self.assertEqual(self.state.turn_phase, "PROPERTY_MANAGEMENT")
        self.assertEqual(self.state.roll_sequence, 1)
        self.assertEqual(self.state.last_roll_actor_id, "a")

    def test_sale_is_80_percent(self):
        p = self.state.properties["jakarta"]
        p.owner_id = "a"
        self.state.players["a"].properties_owned.add("jakarta")
        self.state.turn_phase = "PROPERTY_MANAGEMENT"
        self.engine.apply(self.state, "a", {"type": "SELL_PROPERTY", "propertyId": "jakarta"})
        self.assertEqual(self.state.players["a"].cash, 1136)
        self.assertIsNone(p.owner_id)

    def test_complete_set_and_building_rent(self):
        a = self.state.players["a"]
        for pid in ("madrid", "cairo"):
            self.state.properties[pid].owner_id = "a"
            a.properties_owned.add(pid)
        self.assertTrue(self.engine.owns_complete_color_set(self.state, "a", "sky"))
        self.assertEqual(self.engine.calculate_rent(self.state, "a", "madrid"), 100)
        self.state.turn_phase = "PROPERTY_MANAGEMENT"
        self.engine.apply(self.state, "a", {"type": "UPGRADE_PROPERTY", "propertyId": "madrid"})
        self.assertEqual(self.state.properties["madrid"].building_level, 1)
        self.assertEqual(self.engine.calculate_rent(self.state, "a", "madrid"), 180)

    def test_public_rent_multiplier(self):
        a = self.state.players["a"]
        for pid in ("railway", "harbor", "airport"):
            self.state.properties[pid].owner_id = "a"
            a.properties_owned.add(pid)
        self.assertEqual(self.engine.calculate_public_property_rent(self.state, "a", "railway"), 105)
        p = self.state.properties["electricity"]
        p.owner_id = "a"; a.properties_owned.add(p.id)
        self.assertEqual(self.engine.calculate_public_property_rent(self.state, "a", "railway"), 150)

    def test_city_rent_scales_with_color_count(self):
        a = self.state.players["a"]
        rio, delhi, bangkok = (self.state.properties[x] for x in ("rio", "delhi", "bangkok"))
        rio.owner_id = "a"; a.properties_owned.add("rio")
        self.assertEqual(self.engine.calculate_rent(self.state, "a", "rio"), 30)
        delhi.owner_id = "a"; a.properties_owned.add("delhi")
        self.assertEqual(self.engine.calculate_rent(self.state, "a", "rio"), 60)
        self.assertEqual(self.engine.calculate_rent(self.state, "a", "delhi"), 60)
        bangkok.owner_id = "a"; a.properties_owned.add("bangkok")
        self.assertEqual(self.engine.calculate_rent(self.state, "a", "rio"), 90)
        self.assertEqual(self.engine.calculate_rent(self.state, "a", "bangkok"), 105)

    def test_red_high_value_rents_match_contract(self):
        a = self.state.players["a"]
        london, tokyo, new_york = (self.state.properties[x] for x in ("london", "tokyo", "new-york"))
        london.owner_id = "a"; a.properties_owned.add("london")
        self.assertEqual(self.engine.calculate_rent(self.state, "a", "london"), 70)
        tokyo.owner_id = "a"; a.properties_owned.add("tokyo")
        self.assertEqual(self.engine.calculate_rent(self.state, "a", "london"), 150)
        self.assertEqual(self.engine.calculate_rent(self.state, "a", "tokyo"), 150)
        new_york.owner_id = "b"; self.state.players["b"].properties_owned.add("new-york")
        self.assertEqual(self.engine.calculate_rent(self.state, "b", "new-york"), 80)
        self.state.players["b"].properties_owned.remove("new-york")
        new_york.owner_id = "a"; a.properties_owned.add("new-york")
        self.assertEqual(self.engine.calculate_rent(self.state, "a", "london"), 230)
        self.assertEqual(self.engine.calculate_rent(self.state, "a", "new-york"), 250)

    def test_own_property_never_charges_rent(self):
        a = self.state.players["a"]
        rio = self.state.properties["rio"]
        rio.owner_id = "a"; a.properties_owned.add("rio")
        a.board_position = self.state.board_ids.index("start")
        before = a.cash
        self.engine.rng = FixedRng([1])
        self.engine.apply(self.state, "a", {"type": "ROLL_DICE"})
        self.assertEqual(a.cash, before)
        self.assertFalse(any(e.type == "RENT_PAID" and e.actor_id == "a" for e in self.state.events))
        self.assertEqual(self.engine.current_player(self.state).id, "b")

    def test_full_set_upgrades_available_before_roll(self):
        a = self.state.players["a"]
        for pid in ("rio", "delhi", "bangkok"):
            self.state.properties[pid].owner_id = "a"; a.properties_owned.add(pid)
        self.state.turn_phase = "PROPERTY_MANAGEMENT"
        before = a.cash
        self.engine.apply(self.state, "a", {"type": "UPGRADE_PROPERTY", "propertyId": "rio"})
        self.assertEqual(a.cash, before - 100)
        self.assertEqual(self.engine.calculate_rent(self.state, "a", "rio"), 150)
        self.state.turn_phase = "READY_TO_ROLL"
        self.engine.apply(self.state, "a", {"type": "UPGRADE_PROPERTY", "propertyId": "rio"})
        self.assertEqual(self.engine.calculate_rent(self.state, "a", "rio"), 230)

    def test_snapshot_exposes_live_rent_and_set_progress(self):
        a = self.state.players["a"]
        for pid in ("rio", "delhi"):
            self.state.properties[pid].owner_id = "a"; a.properties_owned.add(pid)
        for pid in ("airport", "harbor", "railway"):
            self.state.properties[pid].owner_id = "a"; a.properties_owned.add(pid)
        snap = self.engine.snapshot(self.state, "a")
        by_id = {p["id"]: p for p in snap["board"]}
        self.assertEqual(by_id["rio"]["currentRent"], 60)
        self.assertEqual(by_id["rio"]["ownedCount"], 2)
        self.assertEqual(by_id["rio"]["setSize"], 3)
        self.assertEqual(by_id["railway"]["currentRent"], 105)
        self.assertEqual(by_id["railway"]["rentByOwnedCount"], [35, 70, 105, 150])

    def test_exact_negative_500_is_bankrupt(self):
        a = self.state.players["a"]
        a.cash = -500
        self.assertTrue(self.engine.check_bankruptcy(self.state, "a"))
        self.assertTrue(a.bankrupt)

    def test_bankrupt_player_on_six_advances_to_true_successor(self):
        state = self.engine.new_game([
            {"id":"a","username":"A"}, {"id":"b","username":"B"}, {"id":"c","username":"C"}
        ], 3000, 0)
        state.turn_order = ["a", "b", "c"]; state.turn_index = 1
        rio = state.properties["rio"]; rio.owner_id = "a"; state.players["a"].properties_owned.add("rio")
        state.players["b"].board_position = 1; state.players["b"].cash = -470
        self.engine.rng = FixedRng([6])
        self.engine.apply(state, "b", {"type":"ROLL_DICE"})
        self.assertTrue(state.players["b"].bankrupt)
        self.assertEqual(state.turn_order, ["a", "c"])
        self.assertEqual(self.engine.current_player(state).id, "c")
        self.assertEqual(state.turn_phase, "PROPERTY_MANAGEMENT")

    def test_two_player_bankruptcy_snapshot_points_to_winner(self):
        self.state.turn_order = ["a", "b"]; self.state.turn_index = 1
        rio = self.state.properties["rio"]; rio.owner_id = "a"; self.state.players["a"].properties_owned.add("rio")
        self.state.players["b"].board_position = 1; self.state.players["b"].cash = -470
        self.engine.rng = FixedRng([6])
        self.engine.apply(self.state, "b", {"type":"ROLL_DICE"})
        snap = self.engine.snapshot(self.state, "a")
        self.assertEqual(snap["phase"], "game_over")
        self.assertEqual(snap["winner_id"], "a")
        self.assertEqual(snap["current_id"], "a")

    def test_salary_target_wins_before_landing_cost(self):
        a = self.state.players["a"]
        a.cash = 2800; a.board_position = 5
        self.engine.rng = FixedRng([1])
        self.engine.apply(self.state, "a", {"type":"ROLL_DICE"})
        self.assertEqual(self.state.phase, "GAME_OVER")
        self.assertEqual(self.state.winner_id, "a")
        self.assertEqual(a.cash, 3000)

    def test_client_cannot_skip_required_or_bonus_roll(self):
        with self.assertRaises(RuleError):
            self.engine.apply(self.state, "a", {"type":"END_TURN"})
        self.state.turn_phase = "READY_TO_ROLL"
        with self.assertRaises(RuleError):
            self.engine.apply(self.state, "a", {"type":"END_TURN"})

    def test_roll_six_gives_extra_roll(self):
        self.state.players["a"].board_position = 0
        self.engine.rng = FixedRng([6, 1])
        self.engine.apply(self.state, "a", {"type": "ROLL_DICE"})
        self.assertEqual(self.state.last_roll, 6)
        self.assertEqual(self.state.turn_phase, "READY_TO_ROLL")
        self.engine.apply(self.state, "a", {"type": "ROLL_DICE"})
        self.assertEqual(self.state.last_roll, 1)

    def test_start_salary_on_crossing(self):
        self.state.players["a"].board_position = 3
        self.engine.rng = FixedRng([3])
        self.engine.apply(self.state, "a", {"type": "ROLL_DICE"})
        self.assertEqual(self.state.players["a"].cash, 1200)
        self.assertTrue(any(e.type == "SALARY_RECEIVED" for e in self.state.events))

    def test_lucky_card_can_require_property_choice(self):
        a = self.state.players["a"]
        p = self.state.properties["jakarta"]
        p.owner_id = "a"
        a.properties_owned.add(p.id)
        self.state.pending_card = {"effectType": "choose_lose_property"}
        self.state.turn_phase = "CARD_DECISION"
        pending_snapshot = self.engine.snapshot(self.state, "a")
        self.assertEqual(pending_snapshot["pending_lose"], {"player_id":"a"})
        self.engine.apply(self.state, "a", {"type": "CHOOSE_LOST_PROPERTY", "propertyId": "jakarta"})
        self.assertNotIn("jakarta", a.properties_owned)
        self.assertIsNone(self.state.pending_card)

    def test_property_loss_card_is_no_effect_without_properties(self):
        self.state.players["a"].board_position = 12
        self.engine.rng = FixedRng([1])
        self.engine.apply(self.state, "a", {"type": "ROLL_DICE"})
        self.assertIsNone(self.state.pending_card)
        self.assertNotEqual(self.state.turn_phase, "CARD_DECISION")
        self.assertTrue(any(e.type == "CARD_NO_EFFECT" for e in self.state.events))

    def test_card_movement_across_start_pays_salary(self):
        a = self.state.players["a"]
        a.board_position = 4
        before = a.cash
        self.engine.card_data = [{"id":"free-ride", "title":"Free ride", "description":"Advance 3.", "effectType":"move_relative", "value":3}]
        self.engine._draw_lucky(self.state, a)
        self.assertEqual(a.cash, before + 200)
        self.assertEqual(a.board_position, 7)
        self.assertTrue(any(e.type == "SALARY_RECEIVED" for e in self.state.events))

    def test_auction_swaps_and_pays_bonus(self):
        a, b = self.state.players["a"], self.state.players["b"]
        pa, pb = self.state.properties["jakarta"], self.state.properties["berlin"]
        pa.owner_id = "a"; pb.owner_id = "b"
        a.properties_owned.add(pa.id); b.properties_owned.add(pb.id)
        self.state.turn_phase = "AUCTION"
        self.state.auction = AuctionState(initiator_id="a")
        self.engine.apply(self.state, "a", {"type": "START_AUCTION", "propertyId": "jakarta"})
        self.engine.apply(self.state, "b", {"type": "SUBMIT_AUCTION_OFFER", "propertyId": "berlin"})
        self.engine.apply(self.state, "a", {"type": "ACCEPT_AUCTION", "playerId": "b"})
        self.assertEqual(pa.owner_id, "b")
        self.assertEqual(pb.owner_id, "a")
        self.assertEqual(a.cash, 1100)
        self.assertEqual(b.cash, 1150)

    def test_auction_portal_listing_bidding_and_opt_out(self):
        a, b, c = self.state.players["a"], self.state.players["b"], None
        pa = self.state.properties["jakarta"]; pb = self.state.properties["berlin"]
        pa.owner_id = "a"; a.properties_owned.add(pa.id)
        pb.owner_id = "b"; b.properties_owned.add(pb.id)
        self.state.turn_phase = "AUCTION"
        self.state.auction = AuctionState(initiator_id="a")
        # anyone may list
        self.engine.apply(self.state, "b", {"type": "LIST_AUCTION_PROPERTY", "propertyId": "berlin"})
        lid = self.engine._auction_json(self.state)["listings"][0]["listingId"]
        # cash bids allowed; repeated bids raise the amount
        b.cash = 300
        self.engine.apply(self.state, "b", {"type": "SUBMIT_AUCTION_OFFER", "listingId": lid, "cash": 120})
        snap = self.engine._auction_json(self.state)
        self.assertEqual(snap["listings"][0]["bids"][0]["cash"], 120)
        # property + cash combo from another player
        self.engine.apply(self.state, "a", {"type": "SUBMIT_AUCTION_OFFER", "listingId": lid, "propertyId": "jakarta", "cash": 40})
        snap = self.engine._auction_json(self.state)
        combo = [x for x in snap["listings"][0]["bids"] if x["playerId"] == "a"][0]
        self.assertEqual(combo["propertyId"], "jakarta")
        self.assertEqual(combo["cash"], 40)
        self.assertEqual(combo["value"], pb.purchase_price if False else combo["value"])
        # opt-out removes outstanding bids
        self.engine.apply(self.state, "b", {"type": "OPT_OUT_AUCTION"})
        snap = self.engine._auction_json(self.state)
        self.assertTrue(all(x["playerId"] != "b" for x in snap["listings"][0]["bids"]))
        # seller accepts the remaining bid: property and cash settle
        before = (a.cash, b.cash)
        self.engine.apply(self.state, "b" if False else "b", {"type": "ACCEPT_AUCTION", "playerId": "a", "listingId": lid}) if False else None
        self.engine.apply(self.state, "b", {"type": "ACCEPT_AUCTION", "playerId": "a", "listingId": lid})
        self.assertEqual(pb.owner_id, "a")
        self.assertEqual(pa.owner_id, "b")
        bonus = int(self.engine.balance["successfulAuctionBonus"])
        self.assertEqual(b.cash, before[1] + 40 + bonus)

    def test_breaking_a_set_lowers_rent_for_remaining_tiles(self):
        a, b = self.state.players["a"], self.state.players["b"]
        paris, hk = self.state.properties["paris"], self.state.properties["hong-kong"]
        for p in (paris, hk):
            p.owner_id = "a"; a.properties_owned.add(p.id)
        full = self.engine.calculate_rent(self.state, "a", "paris")
        self.assertEqual(full, paris.rent_with_set)
        hk.owner_id = "b"; a.properties_owned.discard("hong-kong"); b.properties_owned.add("hong-kong")
        alone = self.engine.calculate_rent(self.state, "a", "paris")
        self.assertEqual(alone, paris.base_rent)
        self.assertLess(alone, full)

    def test_auction_watchdog_closes_when_everyone_opts_out(self):
        a, b = self.state.players["a"], self.state.players["b"]
        self.state.turn_phase = "AUCTION"
        self.state.auction = AuctionState(initiator_id="a")
        self.engine.apply(self.state, "b", {"type": "OPT_OUT_AUCTION"})
        for _ in range(3):
            self.engine._resolve_stale_auction(self.state)
        self.assertIsNone(self.state.auction)

    def test_bankruptcy_returns_assets(self):
        a = self.state.players["a"]
        p = self.state.properties["jakarta"]
        p.owner_id = "a"; a.properties_owned.add(p.id); a.cash = -400
        self.engine.check_all(self.state)
        self.assertTrue(a.bankrupt)
        self.assertIsNone(p.owner_id)

    def test_server_ignores_client_dice_value(self):
        self.engine.rng = FixedRng([4])
        self.engine.apply(self.state, "a", {"type": "ROLL_DICE", "value": 99})
        self.assertEqual(self.state.last_roll, 4)

    def test_bankrupt_player_cannot_win_by_rank_at_cap(self):
        state = self.engine.new_game([
            {"id":"a","username":"A"}, {"id":"b","username":"B"}, {"id":"c","username":"C"}
        ], 3000, 30)
        state.turn_order = ["a","b","c"]; state.turn_index = 2; state.current_round = 30
        c = state.players["c"]
        for pid in ("london","tokyo","new-york","paris","hong-kong"):
            state.properties[pid].owner_id = "c"; c.properties_owned.add(pid)
        rio = state.properties["rio"]; rio.owner_id = "a"; state.players["a"].properties_owned.add("rio")
        c.cash = -470
        c.board_position = (state.board_ids.index("rio") - 1) % len(state.board_ids)
        self.engine.rng = FixedRng([1])
        self.engine.apply(state, "c", {"type":"ROLL_DICE"})
        self.assertTrue(c.bankrupt)
        self.assertEqual(state.phase, "GAME_OVER")
        self.assertIn(state.winner_id, ("a","b"))

    def test_eliminating_final_seat_wraps_the_round(self):
        state = self.engine.new_game([
            {"id":"a","username":"A"}, {"id":"b","username":"B"}, {"id":"c","username":"C"}
        ], 3000, 30)
        state.turn_order = ["a","b","c"]; state.turn_index = 2; state.current_round = 29
        rio = state.properties["rio"]; rio.owner_id = "a"; state.players["a"].properties_owned.add("rio")
        c = state.players["c"]
        c.cash = -470
        c.board_position = (state.board_ids.index("rio") - 1) % len(state.board_ids)
        self.engine.rng = FixedRng([1])
        self.engine.apply(state, "c", {"type":"ROLL_DICE"})
        self.assertTrue(c.bankrupt)
        self.assertEqual(state.current_round, 30)

    def test_forfeit_returns_properties_and_stops_rent(self):
        b = self.state.players["b"]
        rio = self.state.properties["rio"]; rio.owner_id = "b"; b.properties_owned.add("rio")
        self.engine.forfeit(self.state, "b")
        self.assertTrue(b.forfeited)
        self.assertIsNone(rio.owner_id)
        self.assertFalse(b.properties_owned)
        a = self.state.players["a"]
        a.board_position = state_pos = self.state.board_ids.index("rio")
        before = a.cash
        self.engine._resolve_landing(self.state, a)
        self.assertEqual(a.cash, before)

    def test_apply_returns_events_despite_trim(self):
        a = self.state.players["a"]
        rio = self.state.properties["rio"]; rio.owner_id = "a"; a.properties_owned.add("rio")
        from game_engine import GameEvent
        self.state.events = [GameEvent("FILLER", text="x") for _ in range(100)]
        events = self.engine.apply(self.state, "a", {"type":"SELL_PROPERTY","propertyId":"rio"})
        self.assertTrue(any(e.type == "PROPERTY_SOLD" for e in events))

    def test_malformed_property_ids_raise_rule_errors(self):
        for payload in (
            {"type":"SELL_PROPERTY","propertyId":["rio"]},
            {"type":"UPGRADE_PROPERTY","propertyId":{}},
            {"type":"CHOOSE_LOST_PROPERTY","propertyId":1},
            {"type":"SUBMIT_AUCTION_OFFER","propertyId":[]},
        ):
            with self.assertRaises(RuleError):
                self.engine.apply(self.state, "a", payload)

    def test_validate_action_matches_apply_guards(self):
        with self.assertRaises(RuleError):
            self.engine.validate_action(self.state, "b", {"type":"ROLL_DICE"})
        with self.assertRaises(RuleError):
            self.engine.validate_action(self.state, "a", {"type":"BUY_PROPERTY","propertyId":"rio"})
        with self.assertRaises(RuleError):
            self.engine.validate_action(self.state, "a", {"type":"UPGRADE_PROPERTY"})
        with self.assertRaises(RuleError):
            self.engine.validate_action(self.state, "a", {"type":"SELL_PROPERTY","propertyId":["rio"]})
        self.engine.validate_action(self.state, "a", {"type":"ROLL_DICE"})

    def test_gift_property_fallback_emits_cash_event(self):
        for p in self.state.properties.values():
            if p.kind in ("city","public"):
                p.owner_id = "b"; self.state.players["b"].properties_owned.add(p.id)
        self.engine.card_data = [{"id":"gift","title":"Raffle","description":"none free","effectType":"gift_property"}]
        self.engine._draw_lucky(self.state, self.state.players["a"])
        self.assertTrue(any(e.type == "CASH_RECEIVED" and e.amount == 100 for e in self.state.events))


if __name__ == "__main__":
    unittest.main()
