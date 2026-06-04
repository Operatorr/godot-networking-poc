"""
Phase 2 §8.3 — bot-driven regression assertions.

Run after `bot_swarm.aggregate_metrics`. Each assertion takes the per-bot list
plus the active server-side knobs and returns one AssertionResult.

The assertions are designed to:
  * Use only data the bot can independently observe (no server cooperation).
  * Be stable under expected variability (tolerances baked in).
  * Skip cleanly when their preconditions don't hold (e.g. budget assertion
    is a no-op until §1.3 ships per-client rate budgets).

The module is intentionally framework-free so it can be invoked from CI or
imported and re-used from a different harness.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Iterable

from bot_client import OmegaRealmBot


# --- Default knobs (mirror server_config.gd DEFAULTS) -------------------------
# These can be overridden by callers when the server is configured non-default.

DEFAULT_AOI_RADIUS = 700.0
DEFAULT_AOI_EXIT_RADIUS = 800.0
DEFAULT_LOD_NEAR_RADIUS = 400.0
DEFAULT_LOD_MID_RADIUS = 700.0
DEFAULT_LOD_MID_INTERVAL = 2
DEFAULT_LOD_FAR_INTERVAL = 4

# Tolerance (units) added to aoi_exit_radius before flagging a violation.
# Accounts for the race where an entity exits AoI on the same tick we receive
# the snapshot — server still encoded the entity at its just-outside position.
AOI_TOLERANCE_UNITS = 50.0

# Fraction of bots that must individually pass the AoI assertion. <1.0 is
# permissible because a few bots may not yet have a known entity_id during the
# first seconds of a short scenario, leaving max_observed_entity_distance == 0.
AOI_BOT_PASS_RATIO = 0.95

# LOD cadence: ratio of observed median tick gap vs expected interval that
# counts as a pass. Expected gap for FAR entities is `lod_far_interval` ticks;
# we accept observations within ±50% to avoid noise from transient AoI churn.
LOD_GAP_TOLERANCE = 0.5

# Minimum samples required to evaluate per-entity LOD cadence — otherwise the
# entity hasn't been observed long enough for the median to be meaningful.
LOD_MIN_SAMPLES = 6


@dataclass
class AssertionResult:
    name: str
    passed: bool
    message: str
    skipped: bool = False
    details: dict = field(default_factory=dict)


@dataclass
class AssertionConfig:
    """Server-side knobs the assertions need to know about. Pass overrides
    when the server is running non-default config."""
    aoi_radius: float = DEFAULT_AOI_RADIUS
    aoi_exit_radius: float = DEFAULT_AOI_EXIT_RADIUS
    lod_near_radius: float = DEFAULT_LOD_NEAR_RADIUS
    lod_mid_radius: float = DEFAULT_LOD_MID_RADIUS
    lod_mid_interval: int = DEFAULT_LOD_MID_INTERVAL
    lod_far_interval: int = DEFAULT_LOD_FAR_INTERVAL
    # Per-client byte budget (bytes/sec). 0 disables the per-peer budget assertion;
    # populated once §1.3 ships and the harness advertises a budget on CONNECT_AUTH.
    rate_budget_bytes_per_sec: int = 0


# --- Assertions ---------------------------------------------------------------


def assert_aoi_cull(bots: Iterable[OmegaRealmBot], config: AssertionConfig) -> AssertionResult:
    """Every bot's max-observed entity distance must be ≤ aoi_exit_radius + tolerance.

    Bots that never received an entity_id (so couldn't compute distances) are
    excluded; the assertion fails only if too few of the eligible bots passed.
    """
    threshold = config.aoi_exit_radius + AOI_TOLERANCE_UNITS
    eligible = [b for b in bots if b.metrics.max_observed_entity_distance > 0]
    if not eligible:
        return AssertionResult(
            name="aoi_cull",
            passed=True,
            skipped=True,
            message="no bots reported entity observations (not connected long enough?)",
        )

    violators = [(b.bot_id, b.metrics.max_observed_entity_distance) for b in eligible
                 if b.metrics.max_observed_entity_distance > threshold]
    pass_ratio = 1.0 - (len(violators) / len(eligible))
    passed = pass_ratio >= AOI_BOT_PASS_RATIO

    msg_parts = [
        f"max observed entity distance ≤ {threshold:.0f}u",
        f"({len(eligible) - len(violators)}/{len(eligible)} bots, "
        f"worst={max((d for _, d in violators), default=0.0):.1f}u)",
    ]
    return AssertionResult(
        name="aoi_cull",
        passed=passed,
        message=" ".join(msg_parts),
        details={
            "threshold": threshold,
            "eligible_bots": len(eligible),
            "violators": violators[:10],  # cap report size
        },
    )


def _classify_lod_band(distance: float, near_radius: float, mid_radius: float) -> str:
    if distance <= near_radius:
        return "near"
    if distance <= mid_radius:
        return "mid"
    return "far"


def assert_lod_cadence(bots: Iterable[OmegaRealmBot], config: AssertionConfig) -> AssertionResult:
    """Per-band median tick gap between observations should match the configured interval.

    NEAR entities should arrive every snapshot tick (gap≈1). MID/FAR entities
    should arrive every ~lod_mid_interval / lod_far_interval ticks. Today's
    server uses modulo gating; once §1.2 priority queue lands the medians may
    drift but should still cluster near the configured intervals.
    """
    expected = {
        "near": 1,
        "mid": config.lod_mid_interval,
        "far": config.lod_far_interval,
    }
    band_gaps: dict[str, list[int]] = {"near": [], "mid": [], "far": []}

    for bot in bots:
        for entity_id, observations in bot.metrics.entity_observations.items():
            if len(observations) < LOD_MIN_SAMPLES:
                continue
            # Sort by server_tick — observations arrive in order but be defensive.
            sorted_obs = sorted(observations, key=lambda o: o[0])
            for (prev_tick, prev_dist), (cur_tick, cur_dist) in zip(sorted_obs, sorted_obs[1:]):
                gap = cur_tick - prev_tick
                if gap <= 0:
                    continue
                # Use the average distance over the gap to bucket the LOD band —
                # avoids edge-flip flicker classifying a single gap into two bands.
                avg_distance = (prev_dist + cur_dist) * 0.5
                band = _classify_lod_band(avg_distance, config.lod_near_radius, config.lod_mid_radius)
                band_gaps[band].append(gap)

    sample_counts = {b: len(g) for b, g in band_gaps.items()}
    if sum(sample_counts.values()) == 0:
        return AssertionResult(
            name="lod_cadence",
            passed=True,
            skipped=True,
            message="no entity-gap samples collected (run too short?)",
        )

    failures: list[str] = []
    medians: dict[str, float] = {}
    for band, gaps in band_gaps.items():
        if len(gaps) < LOD_MIN_SAMPLES:
            continue
        median = statistics.median(gaps)
        medians[band] = median
        exp = expected[band]
        # Allow median ∈ [exp * (1 - tol), exp * (1 + tol) + 1] — the +1 absorbs
        # the integer-quantization floor for near (expected=1).
        lower = max(1, exp * (1 - LOD_GAP_TOLERANCE))
        upper = exp * (1 + LOD_GAP_TOLERANCE) + 1
        if not (lower <= median <= upper):
            failures.append(f"{band}: median={median:.1f} outside [{lower:.1f}, {upper:.1f}]")

    passed = not failures
    msg = (
        "all LOD bands within ±50% of configured cadence"
        if passed
        else "; ".join(failures)
    )
    return AssertionResult(
        name="lod_cadence",
        passed=passed,
        message=msg,
        details={"medians": medians, "samples": sample_counts, "expected": expected},
    )


def assert_batch_decode_clean(bots: Iterable[OmegaRealmBot], config: AssertionConfig) -> AssertionResult:
    """No bot should encounter an unparseable BATCH frame.

    Any decode failure points to either a server bug (malformed batch) or a
    bot/server protocol drift — both are regressions worth surfacing loudly.
    """
    bots_list = list(bots)
    failing = [(b.bot_id, b.metrics.decode_failures) for b in bots_list if b.metrics.decode_failures > 0]
    total_failures = sum(c for _, c in failing)
    passed = total_failures == 0
    msg = (
        "all batch envelopes decoded cleanly"
        if passed
        else f"{total_failures} decode failure(s) across {len(failing)} bot(s)"
    )
    return AssertionResult(
        name="batch_decode_clean",
        passed=passed,
        message=msg,
        details={"failing_bots": failing[:10]},
    )


def assert_per_peer_budget(bots: Iterable[OmegaRealmBot], config: AssertionConfig,
                           duration_seconds: float) -> AssertionResult:
    """Each bot's average bytes/sec should stay within the advertised budget.

    Skipped until config.rate_budget_bytes_per_sec is non-zero (§1.3 wiring).
    """
    if config.rate_budget_bytes_per_sec <= 0:
        return AssertionResult(
            name="per_peer_budget",
            passed=True,
            skipped=True,
            message="rate budget not configured (gates on Phase 2 §1.3)",
        )

    if duration_seconds <= 0:
        return AssertionResult(
            name="per_peer_budget",
            passed=True,
            skipped=True,
            message="duration is zero",
        )

    budget = config.rate_budget_bytes_per_sec
    violators: list[tuple[int, float]] = []
    for bot in bots:
        rate = bot.metrics.bytes_received / duration_seconds
        if rate > budget:
            violators.append((bot.bot_id, rate))

    passed = not violators
    msg = (
        f"all bots stayed within {budget} B/s"
        if passed
        else f"{len(violators)} bot(s) exceeded {budget} B/s; worst={max(r for _, r in violators):.0f} B/s"
    )
    return AssertionResult(
        name="per_peer_budget",
        passed=passed,
        message=msg,
        details={"budget": budget, "violators": violators[:10]},
    )


# --- Driver -------------------------------------------------------------------


def run_all(bots: list[OmegaRealmBot], duration_seconds: float,
            config: AssertionConfig | None = None) -> list[AssertionResult]:
    """Run every assertion against the bot fleet. Returns results in stable order."""
    cfg = config or AssertionConfig()
    return [
        assert_aoi_cull(bots, cfg),
        assert_lod_cadence(bots, cfg),
        assert_batch_decode_clean(bots, cfg),
        assert_per_peer_budget(bots, cfg, duration_seconds),
    ]


def format_results(results: list[AssertionResult]) -> str:
    """Render a textual report block for inclusion in the swarm summary."""
    lines = ["Regression Assertions:"]
    for r in results:
        if r.skipped:
            tag = "SKIP"
        elif r.passed:
            tag = "PASS"
        else:
            tag = "FAIL"
        lines.append(f"  [{tag}] {r.name}: {r.message}")
    return "\n".join(lines)
