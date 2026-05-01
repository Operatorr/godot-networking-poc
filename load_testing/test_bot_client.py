import math
import struct
import time
import unittest

from bot_client import (
    DELTA_MASK_FLAGS,
    DELTA_MASK_FULL_STATE,
    DELTA_MASK_POSITION,
    DELTA_MASK_REMOVED,
    ENTITY_FLAG_ALIVE,
    ENTITY_FLAG_VISIBLE,
    EntitySnapshot,
    EntityType,
    GameEventType,
    MessageType,
    OmegaRealmBot,
    PLAYER_HITBOX_RADIUS,
    STRATEGY_STATE_FLANK,
    STRATEGY_STATE_HUNT,
    build_header,
    _find_nav_path,
    _movement_hits_obstacle,
    parse_state_update,
)
from bot_swarm import aggregate_metrics

ALIVE_VISIBLE = ENTITY_FLAG_ALIVE | ENTITY_FLAG_VISIBLE


def _full_state_payload(tick: int, entities: list[tuple[int, int, float, float, int, int]]) -> bytes:
    payload = bytearray(struct.pack("<IBB", tick, 0, len(entities)))
    for entity_id, entity_type, x, y, anim, flags in entities:
        payload += struct.pack("<HBhhBB", entity_id, entity_type, int(x * 10), int(y * 10), anim, flags)
    return bytes(payload)


def _delta_payload(tick: int, baseline: int, entries: list[bytes]) -> bytes:
    return struct.pack("<IBIB", tick, 1, baseline, len(entries)) + b"".join(entries)


def _player_info_payload(entity_id: int, name: str, x: float = 0.0, y: float = 0.0) -> bytes:
    encoded = name.encode("utf-8")
    return (
        struct.pack("<BHHH", GameEventType.PLAYER_INFO, 0, entity_id, len(encoded))
        + encoded
        + struct.pack("<hhBBB", int(x * 10), int(y * 10), 255, 255, 255)
    )


class BotClientParserTests(unittest.TestCase):
    def test_full_state_packets_update_snapshot(self):
        states = {}
        payload = _full_state_payload(7, [
            (1, EntityType.PLAYER, 10.5, -2.0, 0, ALIVE_VISIBLE),
            (30000, EntityType.MONSTER, 100.0, 50.0, 0, ALIVE_VISIBLE),
        ])

        parsed = parse_state_update(payload, states)

        self.assertEqual(parsed["server_tick"], 7)
        self.assertEqual(len(parsed["entities"]), 2)
        self.assertAlmostEqual(states[1].x, 10.5)
        self.assertEqual(states[30000].entity_type, EntityType.MONSTER)

    def test_delta_packets_merge_fields(self):
        states = {}
        parse_state_update(_full_state_payload(1, [
            (1, EntityType.PLAYER, 0.0, 0.0, 0, ALIVE_VISIBLE),
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
            (30000, EntityType.MONSTER, 0.0, 0.0, 0, ALIVE_VISIBLE),
        ]), states)

        entry = struct.pack("<HB", 30000, DELTA_MASK_REMOVED)
        parsed = parse_state_update(_delta_payload(2, 1, [entry]), states)

        self.assertEqual(parsed["removed"], [30000])
        self.assertNotIn(30000, states)

    def test_target_selection_prefers_monsters_then_players(self):
        bot = OmegaRealmBot(1, "ws://localhost:8081")
        bot._entity_id = 1
        parse_state_update(_full_state_payload(1, [
            (1, EntityType.PLAYER, 0.0, 0.0, 0, ALIVE_VISIBLE),
            (2, EntityType.PLAYER, 10.0, 0.0, 0, ALIVE_VISIBLE),
            (30000, EntityType.MONSTER, 100.0, 0.0, 0, ALIVE_VISIBLE),
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
            ALIVE_VISIBLE,
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

    def test_difficulty_is_clamped(self):
        self.assertEqual(OmegaRealmBot(1, "ws://localhost:8081", difficulty=-0.25).difficulty, 0.0)
        self.assertEqual(OmegaRealmBot(1, "ws://localhost:8081", difficulty=2.0).difficulty, 1.0)

    def test_target_scoring_requires_valid_visible_targets(self):
        bot = OmegaRealmBot(1, "ws://localhost:8081", difficulty=1.0)
        bot._entity_id = 1
        now = time.monotonic()
        bot._entities = {
            1: EntitySnapshot(1, EntityType.PLAYER, 0.0, 0.0, flags=ALIVE_VISIBLE, last_seen_at=now),
            2: EntitySnapshot(2, EntityType.PLAYER, 30.0, 0.0, flags=ALIVE_VISIBLE, last_seen_at=now),
            30000: EntitySnapshot(30000, EntityType.MONSTER, 50.0, 0.0, flags=ENTITY_FLAG_ALIVE, last_seen_at=now),
            30001: EntitySnapshot(30001, EntityType.MONSTER, 280.0, 0.0, flags=ALIVE_VISIBLE, last_seen_at=now),
        }

        self.assertEqual(bot.select_target(now).entity_id, 30001)

    def test_predictive_aim_leads_moving_targets(self):
        bot = OmegaRealmBot(1, "ws://localhost:8081", difficulty=1.0)
        origin = EntitySnapshot(1, EntityType.PLAYER, 0.0, 0.0, flags=ALIVE_VISIBLE)
        target = EntitySnapshot(30000, EntityType.MONSTER, 400.0, 0.0, flags=ALIVE_VISIBLE, vx=100.0, vy=0.0)

        predicted_x, predicted_y = bot._predict_target_position(target, origin=origin)

        self.assertGreater(predicted_x, target.x)
        self.assertAlmostEqual(predicted_y, target.y, delta=0.001)

    def test_projectile_dodge_chooses_perpendicular_escape(self):
        bot = OmegaRealmBot(1, "ws://localhost:8081", difficulty=1.0)
        origin = EntitySnapshot(1, EntityType.PLAYER, 0.0, 0.0, flags=ALIVE_VISIBLE)
        projectile = EntitySnapshot(
            10000,
            EntityType.PROJECTILE,
            -200.0,
            0.0,
            flags=ENTITY_FLAG_VISIBLE,
            vx=400.0,
            vy=0.0,
        )

        dodge = bot._projectile_dodge_vector(projectile, origin)

        self.assertIsNotNone(dodge)
        self.assertAlmostEqual(dodge[0], 0.0, delta=0.001)
        self.assertGreater(abs(dodge[1]), 0.9)

    def test_strategy_decision_chases_kites_and_shoots(self):
        bot = OmegaRealmBot(1, "ws://localhost:8081", difficulty=1.0)
        bot._entity_id = 1
        now = time.monotonic()
        origin = EntitySnapshot(1, EntityType.PLAYER, 0.0, 0.0, flags=ALIVE_VISIBLE, last_seen_at=now)
        bot._entities = {
            1: origin,
            30000: EntitySnapshot(30000, EntityType.MONSTER, 700.0, 500.0, flags=ALIVE_VISIBLE, last_seen_at=now),
        }

        chase = bot._compute_strategy_decision(now, origin)
        self.assertGreater(chase.move_x, 0.0)

        close_target = EntitySnapshot(30000, EntityType.MONSTER, 80.0, 0.0, flags=ALIVE_VISIBLE, last_seen_at=now)
        bot._entities[30000] = close_target
        kite = bot._compute_strategy_decision(now + 1.0, origin)
        self.assertLess(kite.move_x, 0.0)

        attack_origin = EntitySnapshot(1, EntityType.PLAYER, -500.0, -500.0, flags=ALIVE_VISIBLE, last_seen_at=now)
        in_range = EntitySnapshot(30000, EntityType.MONSTER, -250.0, -500.0, flags=ALIVE_VISIBLE, last_seen_at=now)
        bot._entities[1] = attack_origin
        bot._entities[30000] = in_range
        attack = bot._compute_strategy_decision(now + 2.0, attack_origin)
        self.assertTrue(attack.shoot)

    def test_strategy_aim_uses_projected_fire_origin(self):
        bot = OmegaRealmBot(1, "ws://localhost:8081", difficulty=1.0)
        bot._entity_id = 1
        now = time.monotonic()
        origin = EntitySnapshot(1, EntityType.PLAYER, 0.0, 0.0, flags=ALIVE_VISIBLE, last_seen_at=now)
        target = EntitySnapshot(30000, EntityType.MONSTER, 360.0, 240.0, flags=ALIVE_VISIBLE, last_seen_at=now)
        bot._entities = {1: origin, 30000: target}

        decision = bot._compute_strategy_decision(now, origin)
        fire_x, fire_y = bot._project_fire_origin(origin, decision.move_x, decision.move_y, decision.sprint)
        expected = math.atan2(target.y - fire_y, target.x - fire_x)

        self.assertAlmostEqual(decision.aim_angle, expected, delta=0.001)

    def test_quantized_strategy_velocity_matches_server_input_flags(self):
        bot = OmegaRealmBot(1, "ws://localhost:8081", difficulty=1.0)

        bot._set_velocity_from_direction(0.08, 1.0, sprint=False)

        self.assertEqual(bot._input_flags & 0b1111, 1 << 1)
        self.assertAlmostEqual(bot._vel_x, 0.0)
        self.assertAlmostEqual(bot._vel_y, 200.0)

    def test_batch_packet_unwraps_player_info(self):
        bot = OmegaRealmBot(1, "ws://localhost:8081", difficulty=1.0)
        inner = build_header(MessageType.GAME_EVENT, _player_info_payload(42, bot.character_name, 12.0, -7.0))
        batch = build_header(MessageType.BATCH, struct.pack("<B", 1) + inner)

        bot._handle_message(batch)

        self.assertEqual(bot._entity_id, 42)
        self.assertAlmostEqual(bot._pos_x, 12.0)
        self.assertAlmostEqual(bot._pos_y, -7.0)

    def test_close_stationary_player_aims_at_player(self):
        bot = OmegaRealmBot(1, "ws://localhost:8081", difficulty=1.0)
        bot._entity_id = 1
        now = time.monotonic()
        origin = EntitySnapshot(1, EntityType.PLAYER, -500.0, -500.0, flags=ALIVE_VISIBLE, last_seen_at=now)
        target = EntitySnapshot(2, EntityType.PLAYER, -380.0, -380.0, flags=ALIVE_VISIBLE, last_seen_at=now)
        bot._entities = {1: origin, 2: target}

        decision = bot._compute_strategy_decision(now, origin)
        fire_x, fire_y = bot._project_fire_origin(origin, decision.move_x, decision.move_y, decision.sprint)
        expected = math.atan2(target.y - fire_y, target.x - fire_x)

        self.assertTrue(decision.shoot)
        self.assertAlmostEqual(decision.aim_angle, expected, delta=0.001)

    def test_blocked_target_enters_flank_state(self):
        bot = OmegaRealmBot(1, "ws://localhost:8081", difficulty=1.0)
        bot._entity_id = 1
        now = time.monotonic()
        origin = EntitySnapshot(1, EntityType.PLAYER, -500.0, 0.0, flags=ALIVE_VISIBLE, last_seen_at=now)
        target = EntitySnapshot(2, EntityType.PLAYER, 500.0, 0.0, flags=ALIVE_VISIBLE, last_seen_at=now)
        bot._entities = {1: origin, 2: target}
        bot._blocked_target_id = 2
        bot._blocked_since = now - 2.0

        decision = bot._compute_strategy_decision(now, origin)

        self.assertEqual(decision.state, STRATEGY_STATE_FLANK)
        self.assertTrue(decision.sprint)
        self.assertFalse(decision.shoot)
        self.assertIsNotNone(bot._flank_goal)
        self.assertGreater(len(bot._flank_path), 0)
        self.assertTrue(bot._line_of_fire_clear(bot._flank_goal[0], bot._flank_goal[1], target.x, target.y))

    def test_clear_shot_resets_flank_state(self):
        bot = OmegaRealmBot(1, "ws://localhost:8081", difficulty=1.0)
        bot._entity_id = 1
        now = time.monotonic()
        origin = EntitySnapshot(1, EntityType.PLAYER, -500.0, -500.0, flags=ALIVE_VISIBLE, last_seen_at=now)
        target = EntitySnapshot(2, EntityType.PLAYER, -300.0, -500.0, flags=ALIVE_VISIBLE, last_seen_at=now)
        bot._entities = {1: origin, 2: target}
        bot._blocked_target_id = 2
        bot._blocked_since = now - 2.0
        bot._flank_target_id = 2
        bot._flank_goal = (-300.0, -300.0)

        decision = bot._compute_strategy_decision(now, origin)

        self.assertEqual(decision.state, "engage")
        self.assertTrue(decision.shoot)
        self.assertIsNone(bot._blocked_target_id)
        self.assertIsNone(bot._flank_goal)

    def test_no_target_strategy_enters_hunt_state_and_moves(self):
        bot = OmegaRealmBot(1, "ws://localhost:8081", difficulty=1.0)
        bot._entity_id = 1
        now = time.monotonic()
        origin = EntitySnapshot(1, EntityType.PLAYER, -800.0, -800.0, flags=ALIVE_VISIBLE, last_seen_at=now)
        bot._entities = {1: origin}

        decision = bot._compute_strategy_decision(now, origin)

        self.assertEqual(decision.state, STRATEGY_STATE_HUNT)
        self.assertTrue(decision.sprint)
        self.assertGreater(math.hypot(decision.move_x, decision.move_y), 0.9)
        self.assertIsNotNone(bot._hunt_goal)
        self.assertGreater(len(bot._hunt_path), 0)

    def test_hunt_path_avoids_obstacle_segments(self):
        start = (-500.0, 0.0)
        path = _find_nav_path(start[0], start[1], 500.0, 0.0)

        self.assertGreater(len(path), 1)
        from_x, from_y = start
        for to_x, to_y in path:
            self.assertFalse(_movement_hits_obstacle(from_x, from_y, to_x, to_y, PLAYER_HITBOX_RADIUS))
            from_x, from_y = to_x, to_y


if __name__ == "__main__":
    unittest.main()
