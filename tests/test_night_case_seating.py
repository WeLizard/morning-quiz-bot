"""Free seating (design rule P1, step 5): as many players as came, seats are heroes, the variant follows the seats."""
import copy
import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from domain.night_case_engine import OPEN_SEATING, open_counts, seated_variants, start_open
from domain.night_case_state import decode_state, encode_state, rules_snapshot
from domain.night_case_v2_format import compile_v2, load_v2

ROOT = Path(__file__).resolve().parents[1]
RAW = json.loads((ROOT / "content/night_city/manor_lake.case.json").read_text(encoding="utf8"))
CASE = compile_v2(load_v2((ROOT / "content/night_city/manor_lake.case.json").read_bytes()))
RULES = rules_snapshot("Europe/Berlin")
START = datetime(2026, 11, 15, 10, tzinfo=timezone.utc)
POOL = [f"Житель {i}" for i in range(1, 33)]


def seat(i, hero=None, look=None):
    return {"account_id": f"a{i:02d}", "display_name": f"Игрок {i}", "character_id": hero, "look_id": look}


def begin(players, seed=7):
    return start_open(CASE, RULES, {"players": players, "npc_name_pool": POOL}, game_id="g", seed=seed, now_utc=START)


class FreeSeatingEngineTests(unittest.TestCase):
    def test_three_players_sit_where_they_chose_and_the_rest_is_played_by_the_game(self):
        cook = next(c for c in RAW["characters"] if c["id"] == "cook")
        look = cook["looks"][1]["id"]
        transition = begin([seat(0, "cook", look), seat(1, "investigator"), seat(2)])
        doc = transition.state.document()
        self.assertEqual(doc["sealed"]["composition_id"], OPEN_SEATING)
        self.assertEqual(doc["sealed"]["looks"]["cook"], look)
        heroes = {p["account_id"]: p["character_id"] for p in doc["players"]}
        self.assertEqual((heroes["a00"], heroes["a01"]), ("cook", "investigator"))
        self.assertNotIn(heroes["a02"], {"cook", "investigator"})
        playable = {c["id"] for c in RAW["characters"] if c["can_be_player"]}
        self.assertEqual({n["character_id"] for n in doc["npcs"]} & playable, playable - set(heroes.values()))
        decode_state(encode_state(transition.state), CASE, RULES)

    def test_the_variant_always_leaves_a_seated_human_investigating(self):
        chars = {c["id"]: c for c in RAW["characters"]}
        for seed in range(40):
            doc = begin([seat(0, "lawyer"), seat(1, "housekeeper"), seat(2)], seed).state.document()
            variant = next(v for v in RAW["variants"] if v["id"] == doc["sealed"]["variant_id"])
            self.assertTrue(any(p["character_id"] not in {variant["culprit"], *variant["accomplices"]}
                                and chars[p["character_id"]]["faction"] == "investigation" for p in doc["players"]), seed)

    def test_seats_with_no_possible_investigator_are_refused(self):
        with self.assertRaisesRegex(ValueError, "no variant for seats"):
            begin([seat(0, "lawyer"), seat(1, "gardener"), seat(2, "companion")])

    def test_any_seats_move_to_investigators_when_the_draw_leaves_none(self):
        shadow = [c["id"] for c in RAW["characters"] if c["can_be_player"] and c["faction"] != "investigation"]
        for seed in range(20):
            players = [seat(i, hero) for i, hero in enumerate(shadow[:2])] + [seat(2)]
            doc = begin(players, seed).state.document()
            self.assertTrue(seated_variants(RAW, [p["character_id"] for p in doc["players"]]))

    def test_table_size_hero_and_look_are_checked(self):
        self.assertEqual(open_counts(RAW), list(range(3, 13)))
        for players in ([seat(0), seat(1)], [seat(i) for i in range(13)], [seat(0, "cook"), seat(1, "cook"), seat(2)],
                        [seat(0, "hunter"), seat(1), seat(2)], [seat(0, "cook", "no_such_look"), seat(1), seat(2)],
                        [seat(0, None, "f45"), seat(1), seat(2)]):
            with self.assertRaises(ValueError):
                begin(players)

    def test_open_state_must_stay_inside_the_playable_heroes(self):
        transition = begin([seat(0, "cook"), seat(1, "investigator"), seat(2)])
        doc = copy.deepcopy(transition.state.document())
        doc["sealed"]["assignments"][0]["character_id"] = "hunter"
        with self.assertRaises(ValueError):
            decode_state(json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(), CASE, RULES)


def application_test_url():
    from tests.night_case_test_database import night_case_test_url
    return night_case_test_url()


@unittest.skipUnless(os.environ.get("NIGHT_CASE_TEST_DATABASE_URL"), "needs the owned Night Case PostgreSQL")
class FreeSeatingLobbyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from application.night_case import FrozenCaseRef, NightCaseRegistry, OperatorPrincipal
        from domain.night_case_format import canonical_content_hash
        from storage.database import Database, DatabaseSettings
        from storage.models import Account, Room, RoomMembership
        self.db = Database(DatabaseSettings(url=application_test_url()))
        self.now = START
        self.accounts = [uuid4() for _ in range(4)]
        self.owner = self.accounts[0]; self.room = uuid4().hex
        doc = json.loads((ROOT / "tests/fixtures/night_city/runtime_case_v2.json").read_text(encoding="utf-8"))
        doc["meta"]["id"] = "seat_" + uuid4().hex[:24]
        self.ref = FrozenCaseRef(doc["meta"]["id"], doc["meta"]["version"], canonical_content_hash(doc))
        self.registry = NightCaseRegistry(frozenset({self.ref}), frozenset({"Europe/Berlin"}), b"night-test-cursor-secret-32-bytes!!")
        async with self.db.transaction() as session:
            session.add_all([Account(id=aid, display_name=f"Player {i}") for i, aid in enumerate(self.accounts)])
            await session.flush()
            session.add(Room(id=self.room, kind="standalone", owner_account_id=self.owner)); await session.flush()
            session.add_all([RoomMembership(room_id=self.room, account_id=aid, role="owner" if aid == self.owner else "member") for aid in self.accounts])
            await session.flush()
            await self.service(session).register_case(operator=OperatorPrincipal("test-operator", self.owner), content=doc,
                                                      validation_report={"scope": "synthetic_fixture", "publication": "not_checked"}, admission="rehearsal")

    async def asyncTearDown(self):
        await self.db.dispose()

    def service(self, session):
        from application.night_case import NightCaseApplicationService
        return NightCaseApplicationService(session, lambda: self.now, self.registry)

    def cmd(self, revision, params=None):
        return {"command_id": uuid4().hex, "expected_lobby_revision": revision, "params": params or {}}

    async def call(self, method, account, game, view, params=None):
        async with self.db.transaction() as session:
            return (await getattr(self.service(session), method)(account_id=account, game_id=game, command=self.cmd(view["lobby_revision"], params)))["view"]

    async def test_seats_are_heroes_taken_freed_and_started_with_three(self):
        from application.night_case import NightCaseError
        async with self.db.transaction() as session:
            view = (await self.service(session).create_lobby(account_id=self.owner, room_id=self.room, command=self.cmd(
                0, {"case_id": self.ref.case_id, "case_version": self.ref.case_version, "timezone": "Europe/Berlin"})))["view"]
        game = view["game_id"]
        self.assertEqual(view["seating"], "open")
        self.assertEqual(view["allowed_counts"], list(range(3, 13)))
        self.assertEqual(view["windows"], {"slots": ["09:00", "19:00"], "count": 14})
        self.assertEqual(len(view["heroes"]), 12)
        # Heroes the game always plays: title and public portrait only, never a seat.
        self.assertTrue(all(set(row) == {"id", "title", "art"} for row in view["npc_heroes"]))
        self.assertFalse({row["id"] for row in view["npc_heroes"]} & {row["id"] for row in view["heroes"]})
        for account in self.accounts[1:3]:
            view = await self.call("join_lobby", account, game, view)
        view = await self.call("take_seat", self.owner, game, view, {"character_id": "person_00", "look_id": None})
        with self.assertRaises(NightCaseError) as taken:
            await self.call("take_seat", self.accounts[1], game, view, {"character_id": "person_00", "look_id": None})
        self.assertEqual(taken.exception.code, "seat_taken")
        view = await self.call("take_seat", self.accounts[1], game, view, {"character_id": "person_01", "look_id": None})
        for i, account in enumerate(self.accounts[:3]):
            view = await self.call("set_ready", account, game, view, {"name": f"Player {i}", "address_form": "n", "ready": True})
        view = await self.call("take_seat", self.accounts[1], game, view, {"character_id": None, "look_id": None})
        self.assertFalse(next(s for s in view["seats"] if s["seat"] == "seat02")["ready"], "a new seat asks for readiness again")
        view = await self.call("take_seat", self.accounts[1], game, view, {"character_id": "person_01", "look_id": None})
        view = await self.call("set_ready", self.accounts[1], game, view, {"name": "Player 1", "address_form": "n", "ready": True})
        self.assertTrue(view["can_start"] is False)
        async with self.db.transaction() as session:
            owner_view = await self.service(session).get_view(account_id=self.owner, game_id=game)
        self.assertTrue(owner_view["lobby"]["can_start"])
        # The lobby is dressed like the case: world, style pack and the (possibly absent) art binding, nothing else.
        self.assertEqual(set(owner_view["public"]), {"world", "style_pack", "art"})
        started = await self.call("start_game", self.owner, game, owner_view["lobby"])
        self.assertEqual(started["status"], "running")
        async with self.db.transaction() as session:
            running = await self.service(session).get_view(account_id=self.owner, game_id=game)
            second = await self.service(session).get_view(account_id=self.accounts[1], game_id=game)
        self.assertEqual(running["self"]["character_id"], "person_00")
        self.assertEqual(second["self"]["character_id"], "person_01")

    async def say(self, account, game, text, command_id=None):
        async with self.db.transaction() as session:
            return await self.service(session).post_lobby_message(account_id=account, game_id=game,
                                                                  command={"command_id": command_id or uuid4().hex, "text": text})

    async def test_lobby_talk_is_written_at_the_table_and_read_by_the_company(self):
        """Mockup 4 «Обсуждение»: players at the table write; every company member reads; the line keeps the seat."""
        from datetime import timedelta
        from application.night_case import NightCaseError
        async with self.db.transaction() as session:
            view = (await self.service(session).create_lobby(account_id=self.owner, room_id=self.room, command=self.cmd(
                0, {"case_id": self.ref.case_id, "case_version": self.ref.case_version, "timezone": "Europe/Berlin"})))["view"]
        game = view["game_id"]
        view = await self.call("join_lobby", self.accounts[1], game, view)
        view = await self.call("take_seat", self.accounts[1], game, view, {"character_id": "person_01", "look_id": None})
        revision = view["lobby_revision"]
        first = await self.say(self.accounts[1], game, "  Беру второго. Стартуем вечером?  ", command_id="chat-0001")
        self.assertEqual(first["message"]["text"], "Беру второго. Стартуем вечером?")
        self.assertEqual((first["message"]["name"], first["message"]["character_id"], first["message"]["mine"]), ("Player 1", "person_01", True))
        # The same command is the same line; another text under it is a conflict.
        again = await self.say(self.accounts[1], game, "Беру второго. Стартуем вечером?", command_id="chat-0001")
        self.assertEqual(again["message"]["id"], first["message"]["id"])
        with self.assertRaises(NightCaseError) as conflict:
            await self.say(self.accounts[1], game, "другой текст", command_id="chat-0001")
        self.assertEqual(conflict.exception.code, "command_conflict")
        await self.say(self.owner, game, "Да, в семь.")
        # A member who has not joined reads the talk but cannot write; the talk does not move the lobby revision.
        async with self.db.transaction() as session:
            outsider = await self.service(session).get_view(account_id=self.accounts[3], game_id=game)
        self.assertEqual([row["text"] for row in outsider["lobby"]["chat"]], ["Беру второго. Стартуем вечером?", "Да, в семь."])
        self.assertEqual([row["mine"] for row in outsider["lobby"]["chat"]], [False, False])
        self.assertEqual(outsider["lobby"]["lobby_revision"], revision)
        self.assertNotIn("sender_account_id", outsider["lobby"]["chat"][0])
        with self.assertRaises(NightCaseError) as stranger:
            await self.say(self.accounts[3], game, "Можно мне?")
        self.assertEqual(stranger.exception.code, "unavailable")
        for bad in ("", "   ", "x" * 501, "звонок\x07"):
            with self.assertRaises(NightCaseError) as invalid:
                await self.say(self.owner, game, bad)
            self.assertEqual(invalid.exception.code, "invalid_command")
        # A burst is cut after eight lines a minute; a minute later the sender writes again.
        for i in range(7):
            await self.say(self.owner, game, f"строка {i}")
        with self.assertRaises(NightCaseError) as burst:
            await self.say(self.owner, game, "ещё")
        self.assertEqual((burst.exception.code, burst.exception.status), ("rate_limited", 429))
        self.now = START + timedelta(minutes=2)
        await self.say(self.owner, game, "ещё")
        # After the start the lobby talk is closed.
        view = await self.call("join_lobby", self.accounts[2], game, view)
        view = await self.call("take_seat", self.owner, game, view, {"character_id": "person_00", "look_id": None})
        for i, account in enumerate(self.accounts[:3]):
            view = await self.call("set_ready", account, game, view, {"name": f"Player {i}", "address_form": "n", "ready": True})
        await self.call("start_game", self.owner, game, view)
        with self.assertRaises(NightCaseError) as closed:
            await self.say(self.owner, game, "Поехали")
        self.assertEqual(closed.exception.code, "game_not_lobby")

    async def test_an_open_lobby_is_listed_and_a_stranger_enters_without_a_code(self):
        """Mockup 4 «Открытый сбор»: the owner lists the lobby; a stranger enters the company and sits in the lobby."""
        from application.rooms import RoomApplicationService
        from storage.models import Account, RoomMembership
        stranger, removed = uuid4(), uuid4()
        async with self.db.transaction() as session:
            session.add_all([Account(id=stranger, display_name="Чужой"), Account(id=removed, display_name="Убранный")])
            await session.flush()
            session.add(RoomMembership(room_id=self.room, account_id=removed, role="member", status="removed"))
        async with self.db.transaction() as session:
            view = (await self.service(session).create_lobby(account_id=self.owner, room_id=self.room, command=self.cmd(
                0, {"case_id": self.ref.case_id, "case_version": self.ref.case_version, "timezone": "Europe/Berlin"})))["view"]
        game = view["game_id"]
        async def listed(account=stranger):
            async with self.db.transaction() as session:
                return [row for row in await RoomApplicationService(session).list_open(account_id=account) if row["room_id"] == self.room]
        async def enter(account):
            async with self.db.transaction() as session:
                return await RoomApplicationService(session).join_open_night_case(room_id=self.room, account_id=account)
        self.assertEqual(await listed(), [], "closed by default")
        with self.assertRaises(LookupError):
            await enter(stranger)
        async with self.db.transaction() as session:
            opened = await RoomApplicationService(session).set_open(account_id=self.owner, room_id=self.room, open=True)
        self.assertTrue(opened["open"])
        [row] = await listed()
        self.assertEqual({k: row[k] for k in ("game", "case_title", "host_name", "seated", "needs_from", "capacity", "status", "joined")},
                         {"game": "night_case", "case_title": view["case"]["title"], "host_name": "Player 0", "seated": 1,
                          "needs_from": 3, "capacity": 12, "status": "gathering", "joined": False})
        self.assertFalse({"owner_account_id", "account_id", "roster"} & set(row), "no accounts on the public list")
        entered = await enter(stranger)
        assert entered is not None
        self.assertEqual((entered["joined"], entered["seat"], entered["room"]["role"]), (True, None, "member"))
        self.assertFalse((await enter(stranger))["joined"], "a member entering again is not a new entry")
        with self.assertRaises(PermissionError):
            await enter(removed)
        # The newcomer is a company member: the lobby shows «Присоединиться к столу», and the seat counts on the list.
        view = await self.call("join_lobby", stranger, game, view)
        [row] = await listed()
        self.assertEqual((row["seated"], row["joined"]), (2, True))
        async with self.db.transaction() as session:
            await RoomApplicationService(session).set_open(account_id=self.owner, room_id=self.room, open=False)
        self.assertEqual(await listed(uuid4()), [])
        # A room whose current table is no case lobby leaves the entry to the Mafia table.
        other = uuid4().hex
        async with self.db.transaction() as session:
            from storage.models import Room
            session.add(Room(id=other, kind="standalone", owner_account_id=self.owner)); await session.flush()
            self.assertIsNone(await RoomApplicationService(session).join_open_night_case(room_id=other, account_id=stranger))


class LobbyNameTest(unittest.TestCase):
    """A player without a free display name is «Игрок N» at the table, never the service seat id."""

    def test_empty_or_taken_name_becomes_player_number(self):
        from application.night_case import _lobby_name
        self.assertEqual(_lobby_name("  Вера  ", "seat03", set()), "Вера")
        self.assertEqual(_lobby_name("", "seat02", {"вера"}), "Игрок 2")
        self.assertEqual(_lobby_name("Вера", "seat02", {"вера"}), "Игрок 2")
        self.assertEqual(_lobby_name("Вера", "seat02", {"вера", "игрок 2"}), "Игрок 2.2")


if __name__ == "__main__":
    unittest.main()
