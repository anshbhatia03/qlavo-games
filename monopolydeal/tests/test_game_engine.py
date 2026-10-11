import unittest

from game_engine import GameEngine, RuleError, SUPER_ADMIN_NAMES, make_deck


class MonopolyDealEngineTests(unittest.TestCase):
    def test_standard_deck_counts(self):
        deck = make_deck()
        self.assertEqual(len(deck), 106)  # 110-box deck minus four reference cards
        self.assertEqual(sum(c['kind'] == 'money' for c in deck), 20)
        self.assertEqual(sum(c['kind'] == 'property' and not c.get('wild') for c in deck), 28)
        self.assertEqual(sum(c['kind'] == 'property' and c.get('wild') for c in deck), 11)
        self.assertEqual(sum(c['kind'] in {'action', 'house', 'hotel'} for c in deck), 34)
        self.assertEqual(sum(c['kind'] == 'rent' for c in deck), 13)

    def test_super_admin_names_are_exact_and_only_non_gods_are_peeked(self):
        e = GameEngine(seed=2)
        s = e.new_game([
            {'id': 'a', 'username': 'Ansh Mutthal'},
            {'id': 'b', 'username': 'Micky D'},
            {'id': 'c', 'username': 'KK'},
            {'id': 'd', 'username': 'Ansh'},
        ])
        snap = e.snapshot(s, 'a')
        self.assertTrue(snap['private_viewer'])
        self.assertEqual(set(snap['private_hands']), {'d'})
        self.assertNotIn('b', snap['private_hands'])
        self.assertNotIn('c', snap['private_hands'])
        normal = e.snapshot(s, 'd')
        self.assertNotIn('private_hands', normal)
        self.assertEqual(set(SUPER_ADMIN_NAMES), {'Ansh Mutthal', 'Micky D', 'KK'})

    def test_initial_deal_and_turn_draw(self):
        s = GameEngine(seed=4).new_game([{'id': 'a', 'username': 'A'}, {'id': 'b', 'username': 'B'}])
        self.assertEqual(len(s.players['a'].hand), 7)
        self.assertEqual(len(s.players['b'].hand), 5)
        self.assertEqual(s.plays_left, 3)
        self.assertEqual(s.current_id, 'a')

    def test_properties_and_complete_sets(self):
        e = GameEngine(seed=1)
        s = e.new_game([{'id': 'a', 'username': 'A'}, {'id': 'b', 'username': 'B'}])
        p = s.players['a']
        p.hand = [
            {'id': 'x1', 'kind': 'property', 'title': 'Mediterranean Avenue', 'value': 1, 'colors': ['brown'], 'color': 'brown', 'wild': False},
            {'id': 'x2', 'kind': 'property', 'title': 'Baltic Avenue', 'value': 1, 'colors': ['brown'], 'color': 'brown', 'wild': False},
        ]
        e.apply(s, 'a', {'type': 'play_card', 'card_id': 'x1'})
        e.apply(s, 'a', {'type': 'play_card', 'card_id': 'x2'})
        self.assertEqual(e._complete_sets(p), ['brown'])
        self.assertEqual(e._property_rent(p, 'brown'), 2)

    def test_invalid_property_card_and_illegal_bank(self):
        e = GameEngine(seed=1)
        s = e.new_game([{'id': 'a', 'username': 'A'}, {'id': 'b', 'username': 'B'}])
        prop = {'id': 'ordinary', 'kind': 'property', 'title': 'Test Avenue', 'value': 1, 'colors': ['brown'], 'color': 'brown', 'wild': False}
        s.players['a'].hand.append(prop)
        with self.assertRaises(RuleError):
            e.apply(s, 'a', {'type': 'bank_card', 'card_id': prop['id']})

    def test_rent_and_payment_are_private_and_server_validated(self):
        e = GameEngine(seed=5)
        s = e.new_game([{'id': 'a', 'username': 'A'}, {'id': 'b', 'username': 'B'}])
        a, b = s.players['a'], s.players['b']
        a.properties = [{'id': 'p1', 'kind': 'property', 'title': 'Mediterranean Avenue', 'value': 1, 'colors': ['brown'], 'color': 'brown', 'wild': False, 'assigned_color': 'brown'}, {'id': 'p2', 'kind': 'property', 'title': 'Baltic Avenue', 'value': 1, 'colors': ['brown'], 'color': 'brown', 'wild': False, 'assigned_color': 'brown'}]
        b.bank = [{'id': 'cash', 'kind': 'money', 'title': '$2M', 'value': 2}]
        a.hand = [{'id': 'rent', 'kind': 'rent', 'title': 'Brown / Light Blue Rent', 'value': 1, 'colors': ['brown', 'light blue'], 'wild_rent': False}]
        s.current_id = 'a'; s.plays_left = 3
        e.apply(s, 'a', {'type': 'play_card', 'card_id': 'rent', 'color': 'brown'})
        self.assertEqual(s.pending['type'], 'payment')
        with self.assertRaises(RuleError):
            e.apply(s, 'b', {'type': 'pay', 'card_ids': []})
        e.apply(s, 'b', {'type': 'pay', 'card_ids': ['cash']})
        self.assertIsNone(s.pending)
        self.assertEqual(sum(c['value'] for c in a.bank), 2)

    def test_just_say_no_cancels_targeted_action(self):
        e = GameEngine(seed=8)
        s = e.new_game([{'id': 'a', 'username': 'A'}, {'id': 'b', 'username': 'Ansh Mutthal'}])
        a, b = s.players['a'], s.players['b']
        a.hand = [{'id': 'db', 'kind': 'action', 'title': 'Debt Collector', 'value': 3}]
        b.hand = []
        s.current_id = 'a'; s.plays_left = 3
        e.apply(s, 'a', {'type': 'play_card', 'card_id': 'db', 'target_id': 'b'})
        self.assertTrue(s.pending and s.pending['type'] == 'response')
        e.apply(s, 'b', {'type': 'just_say_no'})
        e.apply(s, 'a', {'type': 'allow'})
        self.assertIsNone(s.pending)
        self.assertEqual(b.hand, [])

    def test_just_say_no_cards_are_reserved_for_present_admins(self):
        e = GameEngine(seed=14)
        s = e.new_game([
            {'id': 'a', 'username': 'Ansh Mutthal'},
            {'id': 'b', 'username': 'Micky D'},
            {'id': 'c', 'username': 'KK'},
            {'id': 'd', 'username': 'Ordinary'},
        ])
        for pid in ['a', 'b', 'c']:
            self.assertEqual(sum(c['title'] == 'Just Say No' for c in s.players[pid].hand), 1)
        self.assertFalse(any(c['title'] == 'Just Say No' for c in s.players['d'].hand))

    def test_admin_just_say_no_is_unlimited_against_ordinary_player(self):
        e = GameEngine(seed=15)
        s = e.new_game([{'id': 'a', 'username': 'Ordinary'}, {'id': 'b', 'username': 'KK'}])
        a, b = s.players['a'], s.players['b']
        a.hand = [{'id': 'db', 'kind': 'action', 'title': 'Debt Collector', 'value': 3}]
        b.hand = []
        s.current_id = 'a'; s.plays_left = 3
        e.apply(s, 'a', {'type': 'play_card', 'card_id': 'db', 'target_id': 'b'})
        e.apply(s, 'b', {'type': 'just_say_no'})
        self.assertEqual(b.hand, [])
        self.assertEqual(s.last_play['cards'][0]['title'], 'Just Say No')
        e.apply(s, 'a', {'type': 'allow'})
        self.assertIsNone(s.pending)
        self.assertEqual(b.bank, [])

    def test_admin_can_stop_ordinary_action_against_another_ordinary_player(self):
        e = GameEngine(seed=16)
        s = e.new_game([
            {'id': 'a', 'username': 'Ordinary A'},
            {'id': 'b', 'username': 'KK'},
            {'id': 'c', 'username': 'Ordinary C'},
        ])
        a, b, c = s.players['a'], s.players['b'], s.players['c']
        a.hand = [{'id': 'db', 'kind': 'action', 'title': 'Debt Collector', 'value': 3}]
        b.hand = []
        c.bank = [{'id': 'cash', 'kind': 'money', 'title': '$1M', 'value': 1}]
        s.current_id = 'a'; s.plays_left = 3
        e.apply(s, 'a', {'type': 'play_card', 'card_id': 'db', 'target_id': 'c'})
        self.assertEqual(s.pending['target_id'], 'b')
        e.apply(s, 'b', {'type': 'just_say_no'})
        e.apply(s, 'a', {'type': 'allow'})
        self.assertIsNone(s.pending)
        self.assertEqual([x['id'] for x in c.bank], ['cash'])

    def test_ordinary_view_has_no_counter_control_or_special_mode(self):
        e = GameEngine(seed=17)
        s = e.new_game([
            {'id': 'a', 'username': 'Ordinary A'},
            {'id': 'b', 'username': 'KK'},
        ])
        a, b = s.players['a'], s.players['b']
        a.hand = [{'id': 'db', 'kind': 'action', 'title': 'Debt Collector', 'value': 3}]
        b.hand = []
        s.current_id = 'a'; s.plays_left = 3
        e.apply(s, 'a', {'type': 'play_card', 'card_id': 'db', 'target_id': 'b'})
        ordinary = e.snapshot(s, 'a')
        self.assertFalse(ordinary['pending']['can_just_say_no'])
        self.assertIsNone(ordinary['pending']['mode'])
        with self.assertRaisesRegex(RuleError, 'Waiting for another player'):
            e.apply(s, 'a', {'type': 'just_say_no'})

    def test_special_counter_does_not_trigger_when_privileged_player_is_actor(self):
        e = GameEngine(seed=18)
        s = e.new_game([
            {'id': 'a', 'username': 'KK'},
            {'id': 'b', 'username': 'Ordinary B'},
        ])
        a, b = s.players['a'], s.players['b']
        a.hand = [{'id': 'db', 'kind': 'action', 'title': 'Debt Collector', 'value': 3}]
        b.hand = []
        b.bank = []; b.properties = []
        s.current_id = 'a'; s.plays_left = 3
        e.apply(s, 'a', {'type': 'play_card', 'card_id': 'db', 'target_id': 'b'})
        self.assertIsNone(s.pending)

    def test_partial_payment_pays_everything_available(self):
        e = GameEngine(seed=6)
        s = e.new_game([{'id': 'a', 'username': 'A'}, {'id': 'b', 'username': 'B'}])
        a, b = s.players['a'], s.players['b']
        a.hand = [{'id': 'debt', 'kind': 'action', 'title': 'Debt Collector', 'value': 3}]
        b.bank = [{'id': 'cash', 'kind': 'money', 'title': '$2M', 'value': 2}]
        s.current_id = 'a'; s.plays_left = 3
        e.apply(s, 'a', {'type': 'play_card', 'card_id': 'debt', 'target_id': 'b'})
        e.apply(s, 'b', {'type': 'pay', 'card_ids': ['cash']})
        self.assertIsNone(s.pending)
        self.assertEqual(b.bank, [])
        self.assertEqual(a.bank[0]['id'], 'cash')

    def test_buildings_survive_property_payment_and_stay_inactive(self):
        e = GameEngine(seed=7)
        s = e.new_game([{'id': 'a', 'username': 'A'}, {'id': 'b', 'username': 'B'}])
        a, b = s.players['a'], s.players['b']
        a.properties = [{'id': 'p1', 'kind': 'property', 'title': 'Mediterranean Avenue', 'value': 1, 'colors': ['brown'], 'color': 'brown', 'wild': False, 'assigned_color': 'brown'}, {'id': 'p2', 'kind': 'property', 'title': 'Baltic Avenue', 'value': 1, 'colors': ['brown'], 'color': 'brown', 'wild': False, 'assigned_color': 'brown'}]
        a.buildings = [{'id': 'h1', 'kind': 'house', 'title': 'House', 'value': 3, 'assigned_color': 'brown', 'active': True}]
        b.hand = [{'id': 'debt', 'kind': 'action', 'title': 'Debt Collector', 'value': 3}]
        s.current_id = 'b'; s.plays_left = 3
        e.apply(s, 'b', {'type': 'play_card', 'card_id': 'debt', 'target_id': 'a'})
        e.apply(s, 'a', {'type': 'pay', 'card_ids': ['p1', 'p2']})
        self.assertEqual(len(a.buildings), 1)
        self.assertFalse(a.buildings[0]['active'])
        self.assertTrue(all('house' not in c and 'hotel' not in c for c in b.properties))

    def test_inactive_building_can_move_without_using_a_play(self):
        e = GameEngine(seed=8)
        s = e.new_game([{'id': 'a', 'username': 'A'}, {'id': 'b', 'username': 'B'}])
        a = s.players['a']
        a.properties = [
            {'id': 'b1', 'kind': 'property', 'title': 'Mediterranean Avenue', 'value': 1, 'colors': ['brown'], 'color': 'brown', 'wild': False, 'assigned_color': 'brown'},
            {'id': 'b2', 'kind': 'property', 'title': 'Baltic Avenue', 'value': 1, 'colors': ['brown'], 'color': 'brown', 'wild': False, 'assigned_color': 'brown'},
            {'id': 'd1', 'kind': 'property', 'title': 'Park Place', 'value': 4, 'colors': ['dark blue'], 'color': 'dark blue', 'wild': False, 'assigned_color': 'dark blue'},
            {'id': 'd2', 'kind': 'property', 'title': 'Boardwalk', 'value': 4, 'colors': ['dark blue'], 'color': 'dark blue', 'wild': False, 'assigned_color': 'dark blue'},
        ]
        a.buildings = [{'id': 'h1', 'kind': 'house', 'title': 'House', 'value': 3, 'assigned_color': 'brown', 'active': False}]
        s.current_id = 'a'; s.plays_left = 2
        e.apply(s, 'a', {'type': 'place_building', 'building_id': 'h1', 'color': 'dark blue'})
        self.assertEqual(s.plays_left, 2)
        self.assertTrue(a.buildings[0]['active'])
        self.assertEqual(e._property_rent(a, 'dark blue'), 11)

    def test_public_snapshot_shows_opponent_table_cards_and_last_play(self):
        e = GameEngine(seed=13)
        s = e.new_game([{'id': 'a', 'username': 'A'}, {'id': 'b', 'username': 'B'}])
        a = s.players['a']
        a.hand = [
            {'id': 'prop', 'kind': 'property', 'title': 'Mediterranean Avenue', 'value': 1, 'colors': ['brown'], 'color': 'brown', 'wild': False},
            {'id': 'action', 'kind': 'action', 'title': 'Just Say No', 'value': 4},
            {'id': 'discarded', 'kind': 'action', 'title': 'Pass Go', 'value': 1},
        ]
        s.current_id = 'a'; s.plays_left = 3
        e.apply(s, 'a', {'type': 'play_card', 'card_id': 'prop'})
        snap = e.snapshot(s, 'b')
        opponent = next(x for x in snap['players'] if x['id'] == 'a')
        self.assertEqual([c['title'] for c in opponent['properties']], ['Mediterranean Avenue'])
        self.assertEqual(snap['last_play']['cards'][0]['title'], 'Mediterranean Avenue')
        self.assertEqual(snap['last_play']['player_id'], 'a')
        e.apply(s, 'a', {'type': 'bank_card', 'card_id': 'action'})
        snap = e.snapshot(s, 'b')
        opponent = next(x for x in snap['players'] if x['id'] == 'a')
        self.assertEqual([c['kind'] for c in opponent['bank']], ['money'])
        self.assertEqual(snap['last_play']['cards'][0]['title'], 'Just Say No')
        self.assertEqual(snap['last_play']['verb'], 'converted to cash')
        e.apply(s, 'a', {'type': 'play_card', 'card_id': 'discarded'})
        snap = e.snapshot(s, 'b')
        self.assertEqual(snap['discard_top']['title'], 'Pass Go')
        self.assertEqual(snap['last_play']['cards'][0]['title'], 'Pass Go')

    def test_discard_down_to_seven(self):
        e = GameEngine(seed=3)
        s = e.new_game([{'id': 'a', 'username': 'A'}, {'id': 'b', 'username': 'B'}])
        s.players['a'].hand.extend(s.players['b'].hand[:3])
        before = len(s.players['a'].hand)
        e.apply(s, 'a', {'type': 'end_turn'})
        self.assertEqual(s.pending['count'], before - 7)
        e.apply(s, 'a', {'type': 'discard', 'card_ids': [c['id'] for c in s.players['a'].hand[:before - 7]]})
        self.assertEqual(len(s.players['a'].hand), 7)
        self.assertEqual(s.current_id, 'b')

    def test_debt_collector_demands_five_million(self):
        e = GameEngine(seed=9)
        s = e.new_game([{'id': 'a', 'username': 'A'}, {'id': 'b', 'username': 'B'}])
        s.players['a'].hand = [{'id': 'debt', 'kind': 'action', 'title': 'Debt Collector', 'value': 3}]
        s.players['b'].bank = [{'id': 'cash', 'kind': 'money', 'title': '$1M', 'value': 1}]
        s.current_id = 'a'; s.plays_left = 3
        e.apply(s, 'a', {'type': 'play_card', 'card_id': 'debt', 'target_id': 'b'})
        self.assertEqual(s.pending['debt']['amount'], 5)

    def test_non_property_cards_banked_as_cash_lose_their_action_identity(self):
        e = GameEngine(seed=10)
        s = e.new_game([{'id': 'a', 'username': 'A'}, {'id': 'b', 'username': 'B'}])
        p = s.players['a']
        p.hand = [
            {'id': 'act', 'kind': 'action', 'title': 'Pass Go', 'value': 1},
            {'id': 'hotel', 'kind': 'hotel', 'title': 'Hotel', 'value': 4},
            {'id': 'rent', 'kind': 'rent', 'title': 'Wild Rent', 'value': 3},
        ]
        s.current_id = 'a'; s.plays_left = 3
        for cid in ['act', 'hotel', 'rent']:
            e.apply(s, 'a', {'type': 'bank_card', 'card_id': cid})
        self.assertEqual(p.hand, [])
        self.assertEqual([c['kind'] for c in p.bank], ['money', 'money', 'money'])
        self.assertEqual([c['title'] for c in p.bank], ['$1M', '$4M', '$3M'])
        self.assertEqual([c['value'] for c in p.bank], [1, 4, 3])

    def test_properties_paid_as_rent_remain_properties_not_cash(self):
        e = GameEngine(seed=11)
        s = e.new_game([{'id': 'a', 'username': 'A'}, {'id': 'b', 'username': 'B'}])
        a, b = s.players['a'], s.players['b']
        a.properties = [{'id': 'rent-prop', 'kind': 'property', 'title': 'Mediterranean Avenue', 'value': 1, 'colors': ['brown'], 'color': 'brown', 'wild': False, 'assigned_color': 'brown'}]
        b.properties = [{'id': 'pay-prop', 'kind': 'property', 'title': 'Baltic Avenue', 'value': 1, 'colors': ['brown'], 'color': 'brown', 'wild': False, 'assigned_color': 'brown'}]
        a.hand = [{'id': 'rent', 'kind': 'rent', 'title': 'Brown / Light Blue Rent', 'value': 1, 'colors': ['brown', 'light blue'], 'wild_rent': False}]
        s.current_id = 'a'; s.plays_left = 3
        e.apply(s, 'a', {'type': 'play_card', 'card_id': 'rent', 'color': 'brown'})
        e.apply(s, 'b', {'type': 'pay', 'card_ids': ['pay-prop']})
        self.assertEqual([c['id'] for c in b.bank], [])
        self.assertEqual([c['id'] for c in a.properties], ['rent-prop', 'pay-prop'])
        self.assertTrue(all(c['kind'] == 'property' for c in a.properties))

    def test_three_complete_sets_also_need_ten_million_cash_to_win(self):
        e = GameEngine(seed=12)
        s = e.new_game([{'id': 'a', 'username': 'A'}, {'id': 'b', 'username': 'B'}])
        p = s.players['a']
        p.properties = [
            {'id': 'b1', 'kind': 'property', 'title': 'Mediterranean Avenue', 'value': 1, 'colors': ['brown'], 'color': 'brown', 'wild': False, 'assigned_color': 'brown'},
            {'id': 'b2', 'kind': 'property', 'title': 'Baltic Avenue', 'value': 1, 'colors': ['brown'], 'color': 'brown', 'wild': False, 'assigned_color': 'brown'},
            {'id': 'lb1', 'kind': 'property', 'title': 'Oriental Avenue', 'value': 1, 'colors': ['light blue'], 'color': 'light blue', 'wild': False, 'assigned_color': 'light blue'},
            {'id': 'lb2', 'kind': 'property', 'title': 'Vermont Avenue', 'value': 1, 'colors': ['light blue'], 'color': 'light blue', 'wild': False, 'assigned_color': 'light blue'},
            {'id': 'lb3', 'kind': 'property', 'title': 'Connecticut Avenue', 'value': 1, 'colors': ['light blue'], 'color': 'light blue', 'wild': False, 'assigned_color': 'light blue'},
            {'id': 'db1', 'kind': 'property', 'title': 'Park Place', 'value': 4, 'colors': ['dark blue'], 'color': 'dark blue', 'wild': False, 'assigned_color': 'dark blue'},
            {'id': 'db2', 'kind': 'property', 'title': 'Boardwalk', 'value': 4, 'colors': ['dark blue'], 'color': 'dark blue', 'wild': False, 'assigned_color': 'dark blue'},
        ]
        e._check_win(s, p)
        self.assertEqual(s.phase, 'playing')
        p.bank = [{'id': 'cash', 'kind': 'money', 'title': '$10M', 'value': 10}]
        e._check_win(s, p)
        self.assertEqual(s.phase, 'game_over')
        self.assertEqual(s.winner_id, 'a')


if __name__ == '__main__':
    unittest.main()
