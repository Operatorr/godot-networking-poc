#!/usr/bin/env python3
"""
Smoke Test - Single-bot integration test for Omega Realm game server.

Connects one bot, sends auth + inputs for 10 seconds, and verifies:
  1. WebSocket connection succeeds
  2. Auth handshake is accepted (bot receives state updates)
  3. Heartbeats are echoed back (RTT measured)
  4. STATE_UPDATE packets are received
  5. SERVER_METRICS packets are received (if server supports them)

Usage:
    python smoke_test.py                          # Default: ws://localhost:8081
    python smoke_test.py --server ws://10.0.0.1:8081
    python smoke_test.py --duration 20            # Run for 20 seconds
"""

import argparse
import asyncio
import logging
import sys
import time

from bot_client import OmegaRealmBot

logger = logging.getLogger("smoke_test")


async def run_smoke_test(server_url: str, duration: int) -> bool:
    """Run a single-bot smoke test. Returns True if all checks pass."""
    bot = OmegaRealmBot(1, server_url)

    # 1. Connect
    logger.info(f"Connecting to {server_url}...")
    connected = await bot.connect(timeout=10.0)
    if not connected:
        logger.error(f"FAIL: Could not connect to {server_url}")
        logger.error(f"  Error: {bot.metrics.last_error}")
        return False
    logger.info(f"OK: Connected in {bot.metrics.connection_time_ms:.0f}ms")

    # 2. Run for duration
    logger.info(f"Running bot for {duration} seconds...")
    await bot.run(duration)

    # 3. Disconnect
    await bot.disconnect()

    # 4. Evaluate results
    m = bot.metrics
    checks = []

    # Check: received state updates
    if m.state_updates_received > 0:
        logger.info(f"OK: Received {m.state_updates_received} state updates")
        checks.append(True)
    else:
        logger.error("FAIL: No state updates received")
        checks.append(False)

    # Check: received heartbeat echoes
    if m.heartbeats_received > 0:
        logger.info(f"OK: Received {m.heartbeats_received} heartbeat echoes (avg RTT: {m.avg_latency:.1f}ms)")
        checks.append(True)
    else:
        logger.error("FAIL: No heartbeat echoes received")
        checks.append(False)

    # Check: packets were sent
    if m.packets_sent > 0:
        logger.info(f"OK: Sent {m.packets_sent} packets ({m.bytes_sent} bytes)")
        checks.append(True)
    else:
        logger.error("FAIL: No packets sent")
        checks.append(False)

    # Check: server tick rate (should be ~30Hz for 10+ seconds)
    if len(m.server_ticks_seen) >= 2:
        ticks = sorted(m.server_ticks_seen)
        tick_range = ticks[-1] - ticks[0]
        est_rate = tick_range / duration if duration > 0 else 0
        logger.info(f"OK: Server tick rate ~{est_rate:.1f} Hz (saw {len(set(m.server_ticks_seen))} unique ticks)")
        checks.append(True)
    else:
        logger.warning("WARN: Not enough server ticks to estimate rate")
        checks.append(True)  # Not a hard failure

    # Check: no disconnection
    if not m.disconnected:
        logger.info("OK: Connection stable (no unexpected disconnect)")
        checks.append(True)
    else:
        logger.error("FAIL: Bot was disconnected unexpectedly")
        checks.append(False)

    # Check: server metrics received (informational, not a hard fail)
    if m.server_metrics_snapshots:
        latest = m.server_metrics_snapshots[-1]
        logger.info(f"OK: Server metrics received - tick_time={latest.get('avg_tick_time_ms', 0):.2f}ms, "
                     f"entities={latest.get('entity_count', 0)}, players={latest.get('player_count', 0)}")
    else:
        logger.info("INFO: No SERVER_METRICS packets received (server may not support it yet)")

    # Check: low error count
    if m.error_count == 0:
        logger.info("OK: No errors during test")
        checks.append(True)
    else:
        logger.warning(f"WARN: {m.error_count} errors during test (last: {m.last_error})")
        checks.append(m.error_count < 3)  # Allow a few transient errors

    # Summary
    passed = all(checks)
    logger.info("")
    if passed:
        logger.info("=== SMOKE TEST PASSED ===")
    else:
        logger.error("=== SMOKE TEST FAILED ===")
    logger.info(f"  Packets: {m.packets_sent} sent / {m.packets_received} received")
    logger.info(f"  Bandwidth: {m.bytes_sent} bytes out / {m.bytes_received} bytes in")
    logger.info(f"  State updates: {m.state_updates_received}")
    logger.info(f"  Heartbeats: {m.heartbeats_received}")
    logger.info(f"  Latency: avg={m.avg_latency:.1f}ms p95={m.p95_latency:.1f}ms")

    return passed


def main():
    parser = argparse.ArgumentParser(description="Omega Realm Smoke Test")
    parser.add_argument("--server", "-s", default="ws://localhost:8081",
                        help="Game server WebSocket URL")
    parser.add_argument("--duration", "-d", type=int, default=10,
                        help="Test duration in seconds (default: 10)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    passed = asyncio.run(run_smoke_test(args.server, args.duration))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
