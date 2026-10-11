import unittest
from fastapi import HTTPException

from app import BotRequest, LeaveRequest, NameRequest, Room, add_bot, broadcast, create_room, leave_room, lobby_snapshot, rooms
from game_engine import GameEngine, RuleError


class FakeSocket:
    def __init__(self):
        self.payloads = []

    async def send_json(self, payload):
        self.payloads.append(payload)


class AppLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        rooms.clear()

    async def test_blank_names_are_rejected_after_cleaning(self):
        with self.assertRaises(HTTPException) as ctx:
            await create_room(NameRequest(name="   "))
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_only_host_can_add_bots(self):
        room = Room("AUTH", players={
            "host": {"id":"host", "username":"Host", "isBot":False},
            "guest": {"id":"guest", "username":"Guest", "isBot":False},
        })
        rooms[room.code] = room
        with self.assertRaises(HTTPException) as ctx:
            await add_bot(room.code, BotRequest(difficulty="normal", player_id="guest"))
        self.assertEqual(ctx.exception.status_code, 403)
        result = await add_bot(room.code, BotRequest(difficulty="normal", player_id="host"))
        self.assertTrue(result["player_id"].startswith("bot"))

    async def test_lobby_tokens_are_on_start(self):
        room = Room("START", players={"host":{"id":"host", "username":"Host", "isBot":False}})
        snap = lobby_snapshot(room, "host")
        start = next(i for i, tile in enumerate(snap["board"]) if tile["kind"] == "start")
        self.assertEqual(snap["players"][0]["pos"], start)

    async def test_lobby_leave_removes_seat_and_transfers_host(self):
        room = Room("LEAVE", players={
            "host":{"id":"host", "username":"Host", "isBot":False},
            "guest":{"id":"guest", "username":"Guest", "isBot":False},
        })
        rooms[room.code] = room
        result = await leave_room(room.code, LeaveRequest(player_id="host"))
        self.assertTrue(result["removed"])
        self.assertNotIn("host", room.players)
        self.assertTrue(lobby_snapshot(room, "guest")["is_host"])

    async def test_broadcast_includes_room_and_host_authority(self):
        room = Room("META", players={
            "host":{"id":"host", "username":"Host", "isBot":False},
            "guest":{"id":"guest", "username":"Guest", "isBot":False},
        })
        host_ws, guest_ws = FakeSocket(), FakeSocket()
        room.sockets = {"host":host_ws, "guest":guest_ws}
        await broadcast(room)
        self.assertTrue(host_ws.payloads[-1]["is_host"])
        self.assertFalse(guest_ws.payloads[-1]["is_host"])
        self.assertEqual(host_ws.payloads[-1]["room"], "META")


class EngineValidationTests(unittest.TestCase):
    def test_duplicate_player_ids_rejected(self):
        engine = GameEngine(seed=1)
        with self.assertRaises(RuleError):
            engine.new_game([
                {"id":"same", "username":"A"},
                {"id":"same", "username":"B"},
            ])

    def test_jail_card_emits_jail_event(self):
        engine = GameEngine(seed=1)
        state = engine.new_game([
            {"id":"a", "username":"A"},
            {"id":"b", "username":"B"},
        ])
        engine.card_data = [{"id":"jail", "title":"Jail", "description":"Go to jail", "effectType":"go_to_jail"}]
        engine._draw_lucky(state, state.players[state.turn_order[0]])
        self.assertTrue(any(event.type == "PLAYER_JAILED" for event in state.events))


if __name__ == "__main__":
    unittest.main()
