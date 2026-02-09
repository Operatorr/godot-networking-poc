#!/usr/bin/env python3
"""
Bot Swarm Orchestrator - Spawns and coordinates multiple OmegaRealmBot instances
for load testing the Omega Realm game server.

Usage:
    python bot_swarm.py --bots 50 --duration 60 --server ws://localhost:8081
    python bot_swarm.py --bots 100 --duration 300 --server ws://10.0.0.1:8081
    python bot_swarm.py --scenario baseline
    python bot_swarm.py --scenario target
    python bot_swarm.py --scenario stress
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime

from bot_client import BotMetrics, OmegaRealmBot

logger = logging.getLogger("bot_swarm")


# --- Predefined Scenarios ---

SCENARIOS = {
    "baseline": {"bots": 50, "duration": 120, "description": "Baseline validation (50 bots, 2 min)"},
    "target": {"bots": 100, "duration": 300, "description": "Target load validation (100 bots, 5 min)"},
    "stress": {"bots": 200, "duration": 300, "description": "Stress test / find breaking point (200 bots, 5 min)"},
}

# Success criteria from the epic
SUCCESS_CRITERIA = {
    "server_fps_min": 30,         # Server must maintain 30+ FPS
    "latency_avg_max_ms": 100,    # Average latency < 100ms
    "latency_p95_max_ms": 150,    # P95 latency < 150ms
    "bandwidth_per_player_max_kbps": 5.0,  # < 5 KB/s per player
    "packet_loss_max_pct": 2.0,   # < 2% packet loss
    "crash_rate_max_pct": 5.0,    # < 5% bot disconnections
}


@dataclass
class AggregatedMetrics:
    """Aggregated metrics from all bots in the swarm."""
    total_bots: int = 0
    connected_bots: int = 0
    disconnected_bots: int = 0
    duration_seconds: float = 0.0

    # Latency
    latency_min_ms: float = 0.0
    latency_max_ms: float = 0.0
    latency_avg_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_p99_ms: float = 0.0

    # Throughput
    total_packets_sent: int = 0
    total_packets_received: int = 0
    total_bytes_sent: int = 0
    total_bytes_received: int = 0
    avg_bandwidth_per_player_kbps: float = 0.0

    # Server health
    avg_state_updates_per_bot: float = 0.0
    estimated_server_tick_rate: float = 0.0
    packet_loss_pct: float = 0.0

    # Errors
    total_errors: int = 0
    crash_rate_pct: float = 0.0


def aggregate_metrics(bots: list[OmegaRealmBot], duration: float) -> AggregatedMetrics:
    """Aggregate metrics from all bots into a single summary."""
    agg = AggregatedMetrics()
    agg.total_bots = len(bots)
    agg.duration_seconds = duration

    if not bots:
        return agg

    all_latencies = []
    all_packet_losses = []
    total_state_updates = 0
    total_ticks = []

    for bot in bots:
        m = bot.metrics
        if m.disconnected:
            agg.disconnected_bots += 1
        else:
            agg.connected_bots += 1

        all_latencies.extend(m.latencies_ms)
        all_packet_losses.append(m.packet_loss_estimate)
        total_state_updates += m.state_updates_received
        total_ticks.extend(m.server_ticks_seen)

        agg.total_packets_sent += m.packets_sent
        agg.total_packets_received += m.packets_received
        agg.total_bytes_sent += m.bytes_sent
        agg.total_bytes_received += m.bytes_received
        agg.total_errors += m.error_count

    # Latency stats
    if all_latencies:
        sorted_lat = sorted(all_latencies)
        agg.latency_min_ms = sorted_lat[0]
        agg.latency_max_ms = sorted_lat[-1]
        agg.latency_avg_ms = sum(sorted_lat) / len(sorted_lat)
        agg.latency_p95_ms = sorted_lat[int(len(sorted_lat) * 0.95)]
        agg.latency_p99_ms = sorted_lat[min(int(len(sorted_lat) * 0.99), len(sorted_lat) - 1)]

    # Bandwidth per player (KB/s)
    if duration > 0 and agg.connected_bots > 0:
        total_bandwidth = (agg.total_bytes_sent + agg.total_bytes_received)
        agg.avg_bandwidth_per_player_kbps = (total_bandwidth / agg.connected_bots / duration) / 1024.0

    # Server tick rate estimate
    if total_ticks:
        unique_ticks = sorted(set(total_ticks))
        if len(unique_ticks) >= 2:
            tick_range = unique_ticks[-1] - unique_ticks[0]
            if duration > 0:
                agg.estimated_server_tick_rate = tick_range / duration

    # State updates per bot
    if agg.total_bots > 0:
        agg.avg_state_updates_per_bot = total_state_updates / agg.total_bots

    # Packet loss
    if all_packet_losses:
        agg.packet_loss_pct = (sum(all_packet_losses) / len(all_packet_losses)) * 100

    # Crash rate
    agg.crash_rate_pct = (agg.disconnected_bots / agg.total_bots) * 100 if agg.total_bots > 0 else 0

    return agg


def evaluate_success(agg: AggregatedMetrics) -> dict[str, dict]:
    """Evaluate aggregated metrics against success criteria."""
    results = {}

    results["latency_avg"] = {
        "criterion": f"Average latency < {SUCCESS_CRITERIA['latency_avg_max_ms']}ms",
        "value": f"{agg.latency_avg_ms:.1f}ms",
        "passed": agg.latency_avg_ms < SUCCESS_CRITERIA["latency_avg_max_ms"],
    }

    results["latency_p95"] = {
        "criterion": f"P95 latency < {SUCCESS_CRITERIA['latency_p95_max_ms']}ms",
        "value": f"{agg.latency_p95_ms:.1f}ms",
        "passed": agg.latency_p95_ms < SUCCESS_CRITERIA["latency_p95_max_ms"],
    }

    results["bandwidth"] = {
        "criterion": f"Bandwidth < {SUCCESS_CRITERIA['bandwidth_per_player_max_kbps']:.1f} KB/s per player",
        "value": f"{agg.avg_bandwidth_per_player_kbps:.2f} KB/s",
        "passed": agg.avg_bandwidth_per_player_kbps < SUCCESS_CRITERIA["bandwidth_per_player_max_kbps"],
    }

    results["packet_loss"] = {
        "criterion": f"Packet loss < {SUCCESS_CRITERIA['packet_loss_max_pct']:.1f}%",
        "value": f"{agg.packet_loss_pct:.2f}%",
        "passed": agg.packet_loss_pct < SUCCESS_CRITERIA["packet_loss_max_pct"],
    }

    results["crash_rate"] = {
        "criterion": f"Bot crash rate < {SUCCESS_CRITERIA['crash_rate_max_pct']:.1f}%",
        "value": f"{agg.crash_rate_pct:.1f}%",
        "passed": agg.crash_rate_pct < SUCCESS_CRITERIA["crash_rate_max_pct"],
    }

    results["server_tick_rate"] = {
        "criterion": f"Server tick rate > {SUCCESS_CRITERIA['server_fps_min']} Hz",
        "value": f"{agg.estimated_server_tick_rate:.1f} Hz",
        "passed": agg.estimated_server_tick_rate >= SUCCESS_CRITERIA["server_fps_min"],
    }

    return results


def generate_report(agg: AggregatedMetrics, server_url: str) -> str:
    """Generate a human-readable performance report."""
    success = evaluate_success(agg)
    all_passed = all(r["passed"] for r in success.values())

    lines = [
        "",
        "=" * 60,
        "  Omega Realm Load Test Report",
        "=" * 60,
        "",
        "Test Configuration:",
        f"  Bot Count:      {agg.total_bots}",
        f"  Duration:        {agg.duration_seconds:.0f} seconds",
        f"  Server:          {server_url}",
        f"  Timestamp:       {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "Connection Summary:",
        f"  Connected:       {agg.connected_bots}",
        f"  Disconnected:    {agg.disconnected_bots}",
        f"  Errors:          {agg.total_errors}",
        "",
        "Server Metrics:",
        f"  Est. Tick Rate:  {agg.estimated_server_tick_rate:.1f} Hz",
        f"  State Updates:   {agg.avg_state_updates_per_bot:.0f} per bot (avg)",
        "",
        "Network Metrics:",
        f"  Packets Sent:    {agg.total_packets_sent:,}",
        f"  Packets Recv:    {agg.total_packets_received:,}",
        f"  Bandwidth/Player:{agg.avg_bandwidth_per_player_kbps:.2f} KB/s",
        "",
        "Latency Distribution:",
        f"  Min:             {agg.latency_min_ms:.1f}ms",
        f"  Avg:             {agg.latency_avg_ms:.1f}ms",
        f"  Max:             {agg.latency_max_ms:.1f}ms",
        f"  P95:             {agg.latency_p95_ms:.1f}ms",
        f"  P99:             {agg.latency_p99_ms:.1f}ms",
        f"  Packet Loss:     {agg.packet_loss_pct:.2f}%",
        "",
        "Success Criteria:",
    ]

    for key, result in success.items():
        icon = "PASS" if result["passed"] else "FAIL"
        lines.append(f"  [{icon}] {result['criterion']}: {result['value']}")

    lines.extend([
        "",
        "-" * 60,
        f"  Conclusion: {'ALL CRITERIA MET' if all_passed else 'SOME CRITERIA FAILED'}",
        "-" * 60,
        "",
    ])

    return "\n".join(lines)


def save_report_json(agg: AggregatedMetrics, bots: list[OmegaRealmBot], server_url: str, filepath: str):
    """Save detailed metrics as JSON for further analysis."""
    success = evaluate_success(agg)
    report = {
        "timestamp": datetime.now().isoformat(),
        "config": {
            "bot_count": agg.total_bots,
            "duration_seconds": agg.duration_seconds,
            "server_url": server_url,
        },
        "aggregated": {
            "connected_bots": agg.connected_bots,
            "disconnected_bots": agg.disconnected_bots,
            "total_errors": agg.total_errors,
            "latency_min_ms": round(agg.latency_min_ms, 1),
            "latency_avg_ms": round(agg.latency_avg_ms, 1),
            "latency_max_ms": round(agg.latency_max_ms, 1),
            "latency_p95_ms": round(agg.latency_p95_ms, 1),
            "latency_p99_ms": round(agg.latency_p99_ms, 1),
            "packet_loss_pct": round(agg.packet_loss_pct, 2),
            "bandwidth_per_player_kbps": round(agg.avg_bandwidth_per_player_kbps, 2),
            "estimated_tick_rate": round(agg.estimated_server_tick_rate, 1),
            "total_packets_sent": agg.total_packets_sent,
            "total_packets_received": agg.total_packets_received,
        },
        "success_criteria": {k: {"passed": v["passed"], "value": v["value"]} for k, v in success.items()},
        "per_bot": [bot.metrics.summary() for bot in bots],
    }

    with open(filepath, "w") as f:
        json.dump(report, f, indent=2)


# --- Swarm Execution ---

async def spawn_bots(count: int, server_url: str, stagger_ms: float = 100) -> list[OmegaRealmBot]:
    """Spawn bots with staggered connections to avoid thundering herd."""
    bots = []
    connected = 0

    for i in range(count):
        bot = OmegaRealmBot(i + 1, server_url)
        success = await bot.connect(timeout=15.0)
        bots.append(bot)

        if success:
            connected += 1
            if (i + 1) % 10 == 0:
                logger.info(f"Connected {connected}/{i + 1} bots...")
        else:
            logger.warning(f"Bot {i + 1} failed to connect")

        # Stagger connections
        if i < count - 1:
            await asyncio.sleep(stagger_ms / 1000.0)

    logger.info(f"Spawned {count} bots, {connected} connected successfully")
    return bots


async def run_load_test(bot_count: int, duration: int, server_url: str, stagger_ms: float = 100) -> tuple[AggregatedMetrics, list[OmegaRealmBot]]:
    """Execute a full load test: spawn bots, run, collect metrics."""
    logger.info(f"Starting load test: {bot_count} bots, {duration}s duration, server={server_url}")

    # Phase 1: Spawn bots
    logger.info("Phase 1: Spawning bots...")
    bots = await spawn_bots(bot_count, server_url, stagger_ms)

    connected_bots = [b for b in bots if b.ws is not None]
    if not connected_bots:
        logger.error("No bots connected! Aborting test.")
        return aggregate_metrics(bots, 0), bots

    logger.info(f"Phase 2: Running test for {duration} seconds with {len(connected_bots)} bots...")

    # Phase 2: Run all bots concurrently
    tasks = [bot.run(duration) for bot in connected_bots]
    await asyncio.gather(*tasks, return_exceptions=True)

    logger.info("Phase 3: Collecting metrics...")

    # Phase 3: Disconnect and collect
    disconnect_tasks = [bot.disconnect() for bot in bots]
    await asyncio.gather(*disconnect_tasks, return_exceptions=True)

    agg = aggregate_metrics(bots, duration)
    return agg, bots


# --- CLI ---

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Omega Realm Load Testing Bot Swarm",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Predefined scenarios:
  baseline  - 50 bots, 2 minutes (validate basic functionality)
  target    - 100 bots, 5 minutes (validate success metrics)
  stress    - 200 bots, 5 minutes (find breaking point)

Examples:
  python bot_swarm.py --scenario baseline --server ws://localhost:8081
  python bot_swarm.py --bots 75 --duration 120 --server ws://10.0.0.1:8081
        """,
    )

    parser.add_argument("--server", "-s", default="ws://localhost:8081",
                        help="Game server WebSocket URL (default: ws://localhost:8081)")
    parser.add_argument("--bots", "-b", type=int, default=None,
                        help="Number of bots to spawn")
    parser.add_argument("--duration", "-d", type=int, default=None,
                        help="Test duration in seconds")
    parser.add_argument("--scenario", choices=SCENARIOS.keys(), default=None,
                        help="Use a predefined test scenario")
    parser.add_argument("--stagger", type=float, default=100,
                        help="Milliseconds between bot connections (default: 100)")
    parser.add_argument("--output", "-o", default=None,
                        help="Save JSON report to file (default: report_<timestamp>.json)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable verbose/debug logging")

    return parser.parse_args()


async def main():
    args = parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Determine bot count and duration
    if args.scenario:
        scenario = SCENARIOS[args.scenario]
        bot_count = args.bots or scenario["bots"]
        duration = args.duration or scenario["duration"]
        logger.info(f"Scenario: {args.scenario} - {scenario['description']}")
    else:
        bot_count = args.bots or 50
        duration = args.duration or 120

    server_url = args.server

    # Run load test
    agg, bots = await run_load_test(bot_count, duration, server_url, args.stagger)

    # Generate report
    report = generate_report(agg, server_url)
    print(report)

    # Save JSON report
    output_path = args.output or f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    save_report_json(agg, bots, server_url, output_path)
    logger.info(f"JSON report saved to: {output_path}")

    # Exit code based on success criteria
    success = evaluate_success(agg)
    all_passed = all(r["passed"] for r in success.values())
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
