import struct
import unittest

from bot_client import (
    DELTA_MASK_FLAGS,
    DELTA_MASK_FULL_STATE,
    DELTA_MASK_POSITION,
    DELTA_MASK_REMOVED,
    ENTITY_FLAG_ALIVE,
    EntityType,
    OmegaRealmBot,
    parse_state_update,
)
from bot_swarm import aggregate_metrics


def _full_state_payload(tick: int, entities: list[tuple[int, int, float, float, int, int]]) -> bytes:
    payload = bytearray(struct.pack("<IBB", tick, 0, len(entities)))
    for entity_id, entity_type, x, y, anim, flags in entities:
        payload += struct.pack("<HBhhBB", entity_id, entity_type, int(x * 10), int(y * 10), anim, flags)
    return bytes(payload)


def _delta_payload(tick: int, baseline: int, entries: list[bytes]) -> bytes:
    return struct.pack("<IBIB", tick, 1, baseline, len(entries)) + b"".join(entries)


class BotClientParserTests(unittest.TestCase):
    def test_full_state_packets_update_snapshot(self):
        states = {}
        payload = _full_state_payload(7, [
            (1, EntityType.PLAYER, 10.5, -2.0, 0, ENTITY_FLAG_ALIVE),
            (30000, EntityType.MONSTER, 100.0, 50.0, 0, ENTITY_FLAG_ALIVE),
        ])

        parsed = parse_state_update(payload, states)

        self.assertEqual(parsed["server_tick"], 7)
        self.assertEqual(len(parsed["entities"]), 2)
        self.assertAlmostEqual(states[1].x, 10.5)
        self.assertEqual(states[30000].entity_type, EntityType.MONSTER)

    def test_delta_packets_merge_fields(self):
        states = {}
        parse_state_update(_full_state_payload(1, [
            (1, EntityType.PLAYER, 0.0, 0.0, 0, ENTITY_FLAG_ALIVE),
        ]), states)

        entry = struct.pack("<HBhhB", 1, DELTA_MASK_POSITION | DELTA_MASK_FLAGS, 25, -40, 0)
        parsed = parse_state_update(_delta_payload(2, 1, [entry]), states)

        self.assertTrue(parsed["is_delta"])
        self.assertAlmostEqual(states[1].x, 2.5)
        self.assertAlmostEqual(states[1].y, -4.0)
        self.assertFalse(states[1].alive)

    def test_entity_removal_markers_delete_snapshot(self):
        states = {}
        parse_state_update(_full_state_payload(1, [
            (30000, EntityType.MONSTER, 0.0, 0.0, 0, ENTITY_FLAG_ALIVE),
        ]), states)

        entry = struct.pack("<HB", 30000, DELTA_MASK_REMOVED)
        parsed = parse_state_update(_delta_payload(2, 1, [entry]), states)

        self.assertEqual(parsed["removed"], [30000])
        self.assertNotIn(30000, states)

    def test_target_selection_prefers_monsters_then_players(self):
        bot = OmegaRealmBot(1, "ws://localhost:8081")
        bot._entity_id = 1
        parse_state_update(_full_state_payload(1, [
            (1, EntityType.PLAYER, 0.0, 0.0, 0, ENTITY_FLAG_ALIVE),
            (2, EntityType.PLAYER, 10.0, 0.0, 0, ENTITY_FLAG_ALIVE),
            (30000, EntityType.MONSTER, 100.0, 0.0, 0, ENTITY_FLAG_ALIVE),
        ]), bot._entities)

        self.assertEqual(bot.select_target().entity_id, 30000)

        parse_state_update(_delta_payload(2, 1, [
            struct.pack("<HB", 30000, DELTA_MASK_REMOVED),
        ]), bot._entities)
        self.assertEqual(bot.select_target().entity_id, 2)

    def test_full_state_delta_entry_adds_entity(self):
        states = {}
        entry = struct.pack(
            "<HBBhhBB",
            30000,
            DELTA_MASK_FULL_STATE,
            EntityType.MONSTER,
            15,
            20,
            0,
            ENTITY_FLAG_ALIVE,
        )
        parse_state_update(_delta_payload(3, 1, [entry]), states)

        self.assertEqual(states[30000].entity_type, EntityType.MONSTER)
        self.assertAlmostEqual(states[30000].x, 1.5)

    def test_aggregate_metrics_uses_recorded_disconnect_state(self):
        healthy_bot = OmegaRealmBot(1, "ws://localhost:8081")
        healthy_bot.ws = None
        healthy_bot.metrics.disconnected = False
        healthy_bot.metrics.bytes_sent = 1024
        healthy_bot.metrics.bytes_received = 1024

        failed_bot = OmegaRealmBot(2, "ws://localhost:8081")
        failed_bot.ws = None
        failed_bot.metrics.disconnected = True

        agg = aggregate_metrics([healthy_bot, failed_bot], 2.0)

        self.assertEqual(agg.connected_bots, 1)
        self.assertEqual(agg.disconnected_bots, 1)
        self.assertEqual(agg.crash_rate_pct, 50.0)
        self.assertEqual(agg.avg_bandwidth_per_player_kbps, 1.0)


if __name__ == "__main__":
    unittest.main()
