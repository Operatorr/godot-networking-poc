"""The production scorer (handoff slice 6, issue #69): sealed recorder files in, separate validity and gate decisions out.

Pure over verified local files, the sealed execution record and the window proof, so a returning controller reaches the same answer from the same bytes.
Nothing here reads a whole-run report: ``report.json`` is carried as a labelled diagnostic and decides nothing. A failed gate is not by itself a capacity
failure, and a missing value is never zero:

  valid_pass               every gate proven, the generator proven valid, and the whole common window proven
  capacity_failure         a failure of the game host demonstrated, with the generator proven valid
  invalid_offered_load     the generator itself failed, and nothing on the server competes with that as an explanation
  infrastructure_failure   the host or the run's execution broke, which says nothing about capacity
  inconclusive_evidence    anything else: missing, foreign or ambiguous evidence, or causes that cannot be separated

What each number really is, traced to its producer (``rust/load_test/src/measured.rs``, ``bot.rs``, ``rust/server/src/main.rs``, ``measurement.rs``, rusty_enet =0.4.0):

  Tick work       ``work_ns`` in ticks.csv: nanoseconds across one ``world.tick``, its outbox flush and ``host.flush``. ENet service between Ticks is not in it.
  Tick time       ``mono_ns`` is that Tick's start, on the server's own monotonic origin.
  RTT             ``peer.round_trip_time()``: ENet's smoothed mean in whole milliseconds, read about once a second per bot. It starts at 500 ms, hence the warmup. Not a raw ping.
  ENet loss       ``peer.packet_loss()``: a smoothed (7/8 old, 1/8 new) estimate of reliable commands retransmitted per command sent, on the scale 65536, updated at most once
                  per 10 s epoch. It is a peer's opinion of reliable traffic and not a measured fraction of datagrams dropped, so it is labelled an estimate everywhere here.
  Peer sample     stamped when the values were read, on the swarm's monotonic origin. Whether it is in the window is decided by that stamp alone.
  Bot disconnect  ``at_ns`` is when the bot's poll saw the event, which can be later than the server's own record. ``reason`` is the data of a server's disconnect command, or 0
                  when ENet gave up by itself. A bot only learns a non-zero reason from the server, so that much of the cause is proven by construction. Reason 0 is ambiguous on
                  its face: ``USER_QUIT`` is also 0, and a server row with reason 0 may be a bot quitting or a server-side timeout.
  Bot ``errors``  ``Bot::fail`` raises it once, so a disconnect the bot did not ask for counts one error. That error is the disconnect, not a second failure.

Boundaries. A Tick or a counter read near an edge of a mapped interval may or may not belong to the window, so a verdict must hold for every position the clocks allow. Tick counts
and socket drops are evaluated at both extremes of that uncertainty, and anything that depends on where the window really was stays unknown.
"""
import contextlib
import fractions
import hashlib
import json
import math
import pathlib
import re

import measurement_window as mw
import search

SCORE_SCHEMA = 'omega.do-session.run-score/1'
SCORER = 'omega.do-session.capacity-scorer/1'
PASS, FAIL, UNKNOWN = 'pass', 'fail', 'unknown'
VALID, INVALID, NOT_PROVEN = 'valid', 'invalid', 'not_proven'
VALID_PASS, CAPACITY_FAILURE, INVALID_LOAD, INFRASTRUCTURE_FAILURE, INCONCLUSIVE = ('valid_pass', 'capacity_failure', 'invalid_offered_load', 'infrastructure_failure', 'inconclusive_evidence')
OUTCOME_OF = {VALID_PASS: search.PASS, CAPACITY_FAILURE: search.FAIL, INVALID_LOAD: search.INVALID_LOAD, INFRASTRUCTURE_FAILURE: search.INFRASTRUCTURE_FAILURE, INCONCLUSIVE: search.INCONCLUSIVE}

TICK_BUDGET_NS = 33_300_000     # the literal 33.3 ms: a Tick of exactly this is not above it
TICK_OVER_PERCENT = 1           # strictly fewer than 1 percent: exactly 1 percent fails
RTT_LIMIT_MS = 150              # strictly below
RTT_QUANTILE_PERCENT = 95
LOSS_SCALE = 65536              # rusty_enet PEER_PACKET_LOSS_SCALE
LOSS_LIMIT = fractions.Fraction(2, 100)     # strictly below
LOSS_BORROW_S = 2               # how far from its one-second bin a bot's reading may still stand for that bin

# Disconnect reasons, as rust/protocol/src/types.rs defines them and rust/server/src ever sends them.
REASON_NONE, REASON_KICKED, REASON_SERVER_SHUTDOWN = 0, 2, 3

# Crash signals a process does not receive from anyone tidying up: it did these to itself. A signal number from Python's negated returncode.
SELF_INFLICTED_SIGNALS = (4, 6, 7, 8, 11)
SIGKILL = 9
RUST_PANIC_EXIT = 101

# A proof reason here means the bytes cannot be trusted to say anything, even a failure.
INTEGRITY_CODES = frozenset((
    'schema_mismatch', 'recorder_overwritten', 'recorder_failed', 'fault_injection_build', 'build_unstated', 'workload_mismatch', 'non_contract_hold', 'ownership_mismatch',
    'process_identity_reused', 'pid_reused', 'process_identity_changed', 'identity_missing', 'socket_identity_changed', 'socket_identity_reused', 'entity_identity_mismatch',
    'schedule_mismatch', 'boundary_contradiction', 'freeze_mismatch', 'window_publish_mismatch', 'window_length_mismatch', 'acknowledged_early', 'socket_counter_reset', 'proof_unreadable', 'prover_failed',
))
# Generator reasons the proof cannot attribute, which this scorer re-derives per bot from the frozen rows. Every other generator reason stands as an independent failure,
# except missing ENet samples: those are missing evidence about the generator, and a starved shard is named by its own reason.
REDERIVED_GENERATOR_CODES = frozenset(('bot_errors', 'offered_input_below_minimum', 'window_not_established', 'peer_sample_coverage'))
CLOCK_BREAKING_CODES = frozenset(('clock_step', 'host_rebooted'))
CONTINUITY_UNKNOWN_CODES = frozenset(('population_boundary_ambiguous', 'server_tick_coverage', 'server_auth_evidence_missing', 'server_tick_gap', 'server_evidence_missing', 'recorder_truncated'))

POLICY = dict(
    tick_budget_ns=TICK_BUDGET_NS, tick_over_percent_strictly_below=TICK_OVER_PERCENT,
    rtt_limit_ms_strictly_below=RTT_LIMIT_MS, rtt_quantile=dict(
        percent=RTT_QUANTILE_PERCENT,
        definition='empirical nearest rank: sort every in-window sample of every bot into one pool of n, take the value at 1-based rank ceil(95 n / 100). No interpolation, and never an average of per-bot quantiles.',
        estimator='ENet smoothed mean round trip time in whole milliseconds'),
    enet_loss=dict(
        limit_strictly_below='2/100', scale=LOSS_SCALE,
        estimator='ENet smoothed reliable-command loss estimate, updated at most once per 10 s epoch. Not a measured fraction of datagrams dropped.',
        definition='one bin per second from the window start. A bot counts once per bin: the mean of its readings in that bin, or else its nearest in-window reading within %d s of the bin, labelled borrowed. A bin\'s value is the mean over the bots still owed there. Every bin must stay strictly below the limit.' % LOSS_BORROW_S,
        borrow_limit_s=LOSS_BORROW_S),
    input=dict(min_percent=mw.schema()['limits']['input_min_percent'],
               definition='per bot: sent over its own scheduled grid slots in the window, in integers. Exactly 99 percent is valid. A disconnected bot is held to the part it was connected for, less the one slot the disconnect can interrupt.'),
    boundaries='Tick counts and socket drops are evaluated over the widest and the narrowest interval the clocks allow. A verdict must hold for both, or it stays unknown.',
)
POLICY_SHA256 = hashlib.sha256(json.dumps(POLICY, sort_keys=True).encode('utf-8')).hexdigest()


def exact(value):
    """A ratio with nothing rounded: the fraction as text, and a float labelled as the convenience it is."""
    return dict(exact='%d/%d' % (value.numerator, value.denominator), approximate=float(value))


def ratio(numerator, denominator):
    return exact(fractions.Fraction(numerator, denominator)) if denominator else None


def nearest_rank(ordered, percent):
    """Value at 1-based rank ceil(percent n / 100), in integers so that no rounding can move the rank."""
    return ordered[(percent * len(ordered) + 99) // 100 - 1]


def _gate(verdict, **facts):
    return dict(verdict=verdict, **facts)


def _sink():
    return mw.Reasons()


# ---- reading what the proof does not carry ----------------------------------------------------------

def peer_samples(root, start, end):
    """Every in-window ENet reading, per bot, plus how many in-window rows could not be used. A reading the recorder botched is reported, never silently dropped."""
    swarm = _load_shards(root)
    found, malformed = {}, []
    for rows in swarm:
        fields = next((row.get('bot_fields') for row in rows if row.get('k') == 'header'), None) or []
        if 'id' not in fields or 'peer' not in fields:
            malformed.append('a shard header does not name its bot fields')
            continue
        at_id, at_peer = fields.index('id'), fields.index('peer')
        for row in rows:
            if row.get('k') not in ('sample', 'drain_end'):
                continue
            for item in row.get('bots') or ():
                if not isinstance(item, list) or len(item) <= max(at_id, at_peer) or not isinstance(item[at_peer], list):
                    continue
                for sample in item[at_peer]:
                    if not (isinstance(sample, list) and len(sample) == 3 and mw.is_count(sample[0])):
                        malformed.append('bot %r: an ENet sample with no time: %r' % (item[at_id], sample))
                    elif start <= sample[0] < end:
                        rtt, loss = sample[1], sample[2]
                        if not mw.is_number(rtt) or not math.isfinite(rtt) or rtt < 0 or not mw.is_count(loss) or loss > LOSS_SCALE:
                            malformed.append('bot %r: an in-window ENet sample of %r and %r' % (item[at_id], rtt, loss))
                        else:
                            found.setdefault(item[at_id], []).append((sample[0], rtt, loss))
    for bot, samples in found.items():
        samples.sort()
        if any(right[0] <= left[0] for left, right in zip(samples, samples[1:])):
            malformed.append('bot %r: two ENet samples at one time' % bot)
    return found, malformed


def _load_shards(root):
    """The shard files that parse. ``load_swarm`` has already said what is wrong with the others."""
    directory = pathlib.Path(root) / 'bot' / 'swarm'
    loaded = []
    for path in sorted(directory.glob('shard-*.ndjson')):
        rows, problem = mw.load_ndjson(path)
        if not problem:
            loaded.append(rows)
    return loaded


def game_exit(execution, sampler_rows):
    """What the game process's exit proves, if it ended before the swarm did. Never more than the exit itself shows."""
    role = ((execution or {}).get('roles') or {}).get('game') or {}
    result = role.get('result') or {}
    if result.get('stop_reason') != 'primary_exited':
        return dict(lost=False)
    item = (result.get('processes') or {}).get('game') or {}
    code, signal = item.get('returncode'), item.get('signal')
    facts = dict(lost=True, returncode=code, signal=signal)
    if code == RUST_PANIC_EXIT:
        return dict(facts, kind='server_panic', demonstrated=True)
    if signal in SELF_INFLICTED_SIGNALS:
        return dict(facts, kind='server_crash_signal', demonstrated=True)
    if signal == SIGKILL:
        oom = _oom_kills(sampler_rows)
        if oom:
            return dict(facts, kind='out_of_memory', demonstrated=True, oom_kills=oom)
        return dict(facts, kind='killed_with_no_cause_on_record', demonstrated=False, oom_kills=oom)
    return dict(facts, kind='ended_with_no_cause_on_record', demonstrated=False)


def _oom_kills(rows):
    """The host's kernel OOM count across the run. Host-wide, so it only ever supports a SIGKILL that already happened, on a host with one load."""
    counts = [row['memory']['oom_kill'] for row in rows if isinstance(row.get('memory'), dict) and mw.is_count(row['memory'].get('oom_kill'))]
    return counts[-1] - counts[0] if len(counts) >= 2 else None


def memory_diagnostics(rows):
    """Memory pressure, which selects a conditional RAM tier and is no gate. Absent on a platform without it."""
    readings = [row['memory'] for row in rows if isinstance(row.get('memory'), dict)]
    if not readings:
        return None

    def spread(key):
        values = [item[key] for item in readings if mw.is_count(item.get(key))]
        return values[-1] - values[0] if len(values) >= 2 else None
    available = [item['MemAvailable'] for item in readings if mw.is_count(item.get('MemAvailable'))]
    return dict(mem_available_min_bytes=min(available) if available else None, oom_kill_delta=spread('oom_kill'), pgmajfault_delta=spread('pgmajfault'), pswpout_delta=spread('pswpout'))


# ---- the common window's gates -----------------------------------------------------------------------

def tick_gate(game, population):
    """Strictly fewer than 1 percent of Ticks above 33.3 ms, for every interval the clocks allow.

    The true interval lies between the narrow and the wide one. The largest ratio it could have is every slow Tick of the wide interval over the Ticks of the narrow one, and
    the smallest is the slow Ticks of the narrow one over the Ticks of the wide one. Only the first being under the limit proves a pass, and only the second reaching it proves a failure.
    """
    wide, narrow = (population or {}).get('interval_game_mono_ns'), (population or {}).get('core_game_mono_ns')
    if game is None or not wide or not narrow:
        return _gate(UNKNOWN, why='no mapped Tick interval')

    def count(low, high):
        inside = [tick for tick in game['ticks'] if low <= tick[0] <= high]
        return len(inside), sum(1 for tick in inside if tick[3] > TICK_BUDGET_NS), inside
    total_wide, over_wide, inside = count(*wide)
    total_narrow, over_narrow, _ = count(*narrow)
    if not total_wide or not total_narrow:
        return _gate(UNKNOWN, why='no Tick in the interval', ticks_wide=total_wide, ticks_narrow=total_narrow)
    work = sorted(tick[3] for tick in inside)
    facts = dict(budget_ns=TICK_BUDGET_NS, ticks_wide=total_wide, ticks_narrow=total_narrow, over_wide=over_wide, over_narrow=over_narrow, worst_possible_ratio=ratio(over_wide, total_narrow),
                 least_possible_ratio=ratio(over_narrow, total_wide), work_ns_max=work[-1], work_ns_p95=nearest_rank(work, 95))
    if over_wide * 100 < total_narrow * TICK_OVER_PERCENT:
        return _gate(PASS, **facts)
    if over_narrow * 100 >= total_wide * TICK_OVER_PERCENT:
        return _gate(FAIL, **facts)
    return _gate(UNKNOWN, why='whether this reaches 1 percent depends on where the clocks put the window', **facts)


def socket_gate(root, proof, limits):
    """Zero drops on the game's own socket, counted between reads that bracket the widest interval. A drop proves an in-window failure only when both reads around it fall inside the narrowest one."""
    facts = proof.get('facts') or {}
    host = facts.get('game_host') or {}
    delta = host.get('socket_drops')
    if not mw.is_count(delta) or (facts.get('game_host_problems') or ()):
        return _gate(UNKNOWN, why='no proven baseline and final read of the game socket', problems=facts.get('game_host_problems'))
    observed = dict(socket_port=host.get('socket_port'), socket_inode=host.get('socket_inode'), drops_in_widest_interval=delta)
    if delta == 0:
        return _gate(PASS, **observed)
    clock = facts.get('clock') or {}
    wide, narrow = clock.get('game_wall_ns'), clock.get('game_core_wall_ns')
    if not wide or not narrow:
        return _gate(UNKNOWN, why='a drop is on record and the interval has no wall mapping', **observed)
    rows = mw.role_window(mw.load_sampler(pathlib.Path(root), 'game', _sink()), wide[0], wide[1], 'game', limits, _sink()) or []
    series = mw.socket_series(rows, 'game').get(host.get('socket_port')) or []
    inside, fringe = 0, 0
    if len(series) == len(rows):
        for left, right, item_left, item_right in zip(rows, rows[1:], series, series[1:]):
            moved = item_right.get('drops', 0) - item_left.get('drops', 0)
            if moved <= 0:
                continue
            before, after = mw.counter_read_bounds(left, limits), mw.counter_read_bounds(right, limits)
            if before is not None and after is not None and before[0] >= narrow[0] and after[1] <= narrow[1]:
                inside += moved
            else:
                fringe += moved
    observed.update(drops_proven_inside=inside, drops_at_the_uncertain_edge=fringe)
    if inside:
        return _gate(FAIL, **observed)
    return _gate(UNKNOWN, why='every drop on record may have fallen just outside the window', **observed)


def rtt_gate(samples, expected_bots, malformed):
    pool = sorted(sample[1] for bot in expected_bots for sample in samples.get(bot) or ())
    if malformed:
        return _gate(UNKNOWN, why='unusable in-window ENet samples', malformed=malformed[:5])
    if not pool or any(not samples.get(bot) for bot in expected_bots):
        return _gate(UNKNOWN, why='a bot has no in-window RTT sample', samples=len(pool), bots_without_samples=[bot for bot in expected_bots if not samples.get(bot)][:10])
    rank = (RTT_QUANTILE_PERCENT * len(pool) + 99) // 100
    value = pool[rank - 1]
    counts = [len(samples[bot]) for bot in expected_bots]
    facts = dict(estimator=POLICY['rtt_quantile']['estimator'], samples=len(pool), bots=len(expected_bots), samples_per_bot_min=min(counts), samples_per_bot_max=max(counts), rank=rank, p95_ms=value, max_ms=pool[-1], limit_ms=RTT_LIMIT_MS)
    return _gate(PASS if value < RTT_LIMIT_MS else FAIL, **facts)


def loss_bins(samples, owed_until, start, hold_s):
    """Per-second equal-bot-weighted values, in exact fractions.

    ``owed_until`` maps each bot to the first bin it no longer owes a reading for: the bin after the one it was seen to disconnect in, or ``hold_s``.
    """
    bins = []
    for k in range(hold_s):
        low, high = start + k * mw.NS, start + (k + 1) * mw.NS
        values, borrowed, missing = [], [], []
        for bot, until in owed_until.items():
            if k >= until:
                continue
            readings = samples.get(bot) or ()
            present = [sample[2] for sample in readings if low <= sample[0] < high]
            if present:
                values.append(fractions.Fraction(sum(present), len(present) * LOSS_SCALE))
                continue
            nearest = None
            for sample in readings:
                distance = low - sample[0] if sample[0] < low else sample[0] - high + 1
                if distance <= LOSS_BORROW_S * mw.NS and (nearest is None or distance < nearest[0]):
                    nearest = (distance, sample[2])
            if nearest is None:
                missing.append(bot)
            else:
                values.append(fractions.Fraction(nearest[1], LOSS_SCALE))
                borrowed.append(bot)
        bins.append(dict(second=k, bots=len(values), borrowed=len(borrowed), missing=missing, value=sum(values, fractions.Fraction(0)) / len(values) if values and not missing else None))
    return bins


def loss_gate(samples, owed_until, start, hold_s, malformed):
    if malformed:
        return _gate(UNKNOWN, why='unusable in-window ENet samples', estimator=POLICY['enet_loss']['estimator'], malformed=malformed[:5])
    bins = loss_bins(samples, owed_until, start, hold_s)
    known = [item for item in bins if item['value'] is not None]
    uncovered = [item['second'] for item in bins if item['value'] is None]
    peers = [(sample[2], bot, sample[0]) for bot, readings in samples.items() for sample in readings]
    facts = dict(estimator=POLICY['enet_loss']['estimator'], seconds=hold_s, seconds_evaluated=len(known), seconds_without_coverage=uncovered[:20], borrowed_readings=sum(item['borrowed'] for item in bins), readings=len(peers))
    if peers:
        worst = max(peers)
        facts['peer_peak'] = dict(ratio=exact(fractions.Fraction(worst[0], LOSS_SCALE)), bot=worst[1], at_bot_mono_ns=worst[2])
    if known:
        peak = max(known, key=lambda item: item['value'])
        facts['per_second_mean_peak'] = dict(ratio=exact(peak['value']), second=peak['second'], bots=peak['bots'])
        facts['window_mean_of_seconds'] = exact(sum((item['value'] for item in known), fractions.Fraction(0)) / len(known))
        facts['seconds_at_or_above_limit'] = [item['second'] for item in known if item['value'] >= LOSS_LIMIT][:20]
        if peak['value'] >= LOSS_LIMIT:
            return _gate(FAIL, **facts)
    if uncovered or not known:
        return _gate(UNKNOWN, why='a second has a bot with no reading near it', **facts)
    return _gate(PASS, **facts)


# ---- bots, disconnects and who caused them ------------------------------------------------------------

def mapper(root, swarm, game):
    """Moves a server monotonic reading to the swarm's clock, as an interval. None when the clocks cannot say."""
    brackets = {label: mw.load_json(pathlib.Path(root) / ('clock-%s.json' % label))[0] for label in ('before', 'after')}
    offset_bot, offset_game = mw.host_offset(brackets, 'bot', _sink()), mw.host_offset(brackets, 'game', _sink())
    if game is None or offset_bot is None or offset_game is None:
        return lambda mono: None

    def move(mono):
        wall = game['domain'].to_wall(mono)
        if wall is None:
            return None
        return swarm['domain'].to_mono(wall[0] - offset_game[1] + offset_bot[0], wall[1] - offset_game[0] + offset_bot[1])
    return move


def server_departures(game):
    """The server's own record of each authenticated bot leaving, by bot number. The first row wins, as the first is the one that broke N."""
    found = {}
    for row in (game or {}).get('population') or ():
        name = row.get('name')
        if row.get('k') == 'disconnect' and isinstance(name, str):
            match = re.fullmatch(r'LoadBot(\d+)', name)
            if match and mw.is_count(row.get('mono_ns')):
                found.setdefault(int(match.group(1)), row)
    return found


def slots_before(at_ns, start, interval_ns):
    """An upper bound on the grid slots this bot owed in ``[start, at_ns)``, whatever its anchor."""
    return (max(at_ns, start) - start) // interval_ns + 1


def bot_facts(swarm, departures, move, interval_ns, limits):
    """Per bot, every count kept, with disconnect lag separated from the server's event time. Nothing in here assigns blame; ``attribute`` does."""
    rows, missing = [], []
    start, end = swarm['start'], swarm['end']
    percent = limits['input_min_percent']
    for shard in swarm['shard_facts']:
        for bot in shard['expected']:
            row = shard['frozen'].get(bot)
            problems = mw.frozen_problems(row, start, end) if row is not None else ['no frozen row']
            if problems:
                missing.append(dict(bot=bot, problems=problems))
                continue
            scheduled, sent = row['scheduled'], row['sent']
            disconnected = row['disconnected']
            item = dict(bot=bot, scheduled=scheduled, sent=sent, send_errors=row['send_errors'], errors=row['errors'], panics=row['panics'], decode_failures=row['decode_failures'], dead_frames=row['dead_frames'], gap_max_ns=row['gap_max_ns'],
                        socket_send_errors=row['socket_send_errors'], socket_zero_sends=row['socket_zero_sends'], socket_receive_errors=row['socket_receive_errors'], ratio=ratio(sent, scheduled))
            if disconnected is None:
                item['input_floor_met'] = sent * 100 >= scheduled * percent
            else:
                owed = row['scheduled_before_disconnect']
                item['disconnect'] = lost = dict(observed_at_bot_mono_ns=disconnected['at_ns'], reason=disconnected['reason'], expected=disconnected['expected'], scheduled_before_observation=owed, last_input_ns=row.get('last_input_ns'))
                item['input_floor_met'] = (sent + 1) * 100 >= owed * percent
                departure = departures.get(bot)
                if departure is not None:
                    lost.update(server_reason=departure.get('reason'), server_at_game_mono_ns=departure['mono_ns'])
                    moved = move(departure['mono_ns'])
                    if moved is not None:
                        low, high = moved
                        lost['server_event_bot_mono_ns'] = [low, high]
                        lost['observation_lag_ns'] = [disconnected['at_ns'] - high, disconnected['at_ns'] - low]
                        lost['order'] = 'server_first' if high <= disconnected['at_ns'] else ('bot_first' if disconnected['at_ns'] < low else 'unresolved')
                        if not item['input_floor_met']:
                            # The bot may have seen it late. What it owes is what fell due before the server's event could have happened, and frames after it are not owed.
                            owed_to_server = min(owed, slots_before(high, start, interval_ns))
                            lost['scheduled_before_server_event'] = owed_to_server
                            item['input_floor_met'] = (sent + 1) * 100 >= owed_to_server * percent
                            item['input_missing_only_after_the_server_event'] = item['input_floor_met']
                lost.setdefault('order', 'server_event_unmapped' if departure is not None else 'no_server_record')
            rows.append(item)
    return rows, missing


def attribute(rows, departures, core, swarm_end, game_lost, tick_verdict, drop_verdict):
    """Which of the departures in this window the evidence shows the server caused. Causality is proven here or stays unknown.

    A kick is proven: only the server can put that reason on the wire. A transport timeout is not: the server, the path or a stalled bot could each produce it, so it needs
    the server's own distress beside it. A reason meaning someone stopped the server, or a refused session, is not a capacity signal at all.
    """
    in_window, departed = [], set()
    for row in rows:
        lost = row.get('disconnect')
        if lost is None or lost['expected']:
            continue
        departed.add(row['bot'])
        if lost['observed_at_bot_mono_ns'] < swarm_end:
            in_window.append(dict(bot=row['bot'], source='bot', **{key: lost.get(key) for key in ('reason', 'server_reason', 'order', 'observation_lag_ns')}))
    low, high = core if core else (None, None)
    if low is not None:
        for bot, departure in departures.items():
            if bot not in departed and low <= departure['mono_ns'] <= high:
                in_window.append(dict(bot=bot, source='server_only', reason=None, server_reason=departure.get('reason'), order='no_bot_observation', observation_lag_ns=None))
    corroborated = game_lost or tick_verdict == FAIL or drop_verdict == FAIL
    for item in in_window:
        reason = item['reason']
        if reason == REASON_KICKED:
            item['cause'] = 'server_kick'
        elif reason == REASON_SERVER_SHUTDOWN:
            item['cause'] = 'server_shutdown_request'
        elif reason not in (None, REASON_NONE):
            item['cause'] = 'reason_is_not_a_capacity_signal'
        elif corroborated:
            item['cause'] = 'transport_timeout_with_server_distress'
        else:
            item['cause'] = 'transport_timeout_unattributed'
    return in_window


# ---- whole documents ----------------------------------------------------------------------------------

def _admissible(evidence, proof):
    """Whether this evidence was produced the way production must produce it. A local shortcut can pass a test; it can never pass a run."""
    problems = []
    if not isinstance(proof, dict) or proof.get('schema') != mw.PROOF_SCHEMA:
        return [dict(code='no_window_proof', detail='there is no window proof of the frozen schema')]
    frozen = dict(id=mw.schema()['id'], sha256=mw.schema_sha256())
    if proof.get('measurement_schema') != frozen['id'] or proof.get('measurement_schema_sha256') != frozen['sha256']:
        problems.append(dict(code='proof_schema_mismatch', detail='the proof was made under %s %s' % (proof.get('measurement_schema'), proof.get('measurement_schema_sha256'))))
    telemetry = evidence.get('telemetry_schema')
    if not isinstance(telemetry, dict) or telemetry.get('id') != frozen['id'] or telemetry.get('sha256') != frozen['sha256']:
        problems.append(dict(code='manifest_schema_mismatch', detail='the manifest froze %r' % (telemetry,)))
    facts = proof.get('facts') if isinstance(proof.get('facts'), dict) else {}
    if facts.get('telemetry_schema_checked') is not True:
        problems.append(dict(code='schema_check_bypassed', detail='the prover was not given the manifest\'s schema to check'))
    if proof.get('socket_counters_required') is not True:
        problems.append(dict(code='socket_counter_bypass', detail='the prover was told that kernel socket counters are optional: a local allowance, never a scored run'))
    if facts.get('contract_hold') is not True:
        problems.append(dict(code='non_contract_hold', detail='a %r s hold is not an accepted window' % (facts.get('hold_s'),)))
    trial = evidence.get('trial') or {}
    if facts.get('target') != trial.get('target') or facts.get('hold_s') != trial.get('hold_s'):
        problems.append(dict(code='proof_is_of_another_trial', detail='the proof says target %r hold %r' % (facts.get('target'), facts.get('hold_s'))))
    if not evidence.get('window_proof_sha256'):
        problems.append(dict(code='proof_not_retained', detail='no retained window proof to bind this score to'))
    execution = evidence.get('execution')
    if not isinstance(execution, dict) or not isinstance(execution.get('problems'), dict):
        problems.append(dict(code='execution_record_missing', detail='no sealed execution record'))
        return problems
    exported = execution.get('exported') or {}
    for role in mw.ROLES:
        if (exported.get(role) or {}).get('complete') is not True:
            problems.append(dict(code='export_incomplete', detail='%s evidence was not verified locally: %r' % (role, (exported.get(role) or {}).get('failed'))))
    return problems


def _legacy(root):
    """Retained beside the scored facts so nobody has to wonder. It covers the ramp and the drain, and it decides nothing."""
    report, problem = mw.load_json(pathlib.Path(root) / 'bot' / 'report.json')
    if problem:
        return dict(present=False, decides_nothing=True)
    return dict(present=True, decides_nothing=True, labelled_whole_run=report.get('legacy_whole_run_diagnostic') is True, measured_window_status=report.get('measured_window_status'))


def _codes(proof):
    if not isinstance(proof, dict):
        return []
    return sorted({item.get('code') for item in proof.get('reasons') or () if isinstance(item, dict)})


def _generator_reasons(proof):
    return sorted({item.get('code') for item in (proof or {}).get('reasons') or () if isinstance(item, dict) and item.get('category') == mw.GENERATOR})


def evaluate(evidence):
    """The whole score document for one run. Every gate is computed even when the run cannot count, so a refused run still shows what it measured."""
    proof = evidence.get('window_proof')
    root = pathlib.Path(evidence['root'])
    trial = evidence['trial']
    workload = evidence.get('workload') or {}
    limits = mw.schema()['limits']
    execution = evidence.get('execution') if isinstance(evidence.get('execution'), dict) else {}
    refused = _admissible(evidence, proof)
    facts = dict(proof.get('facts') or {}) if isinstance(proof, dict) else {}
    document = dict(schema=SCORE_SCHEMA, scorer=SCORER, policy=POLICY, policy_sha256=POLICY_SHA256, run_id=evidence.get('run_id'), establishes_capacity=False,
                    trial={key: trial.get(key) for key in ('ordinal', 'phase', 'target', 'repetition', 'hold_s')},
                    inputs=dict(execution_sha256=evidence.get('execution_sha256'), window_proof_sha256=evidence.get('window_proof_sha256'), measurement_schema=(proof or {}).get('measurement_schema') if isinstance(proof, dict) else None,
                                measurement_schema_sha256=(proof or {}).get('measurement_schema_sha256') if isinstance(proof, dict) else None, proof_status=(proof or {}).get('status') if isinstance(proof, dict) else None, proof_reasons=_codes(proof), inadmissible=refused),
                    legacy_report=_legacy(root))
    infrastructure = list((execution.get('problems') or {}).get('infrastructure') or ())
    window, _ = mw.load_json(root / 'bot' / 'swarm' / 'window.json')
    established = isinstance(window, dict) and window.get('status') != 'not_established' and 'window_not_established' not in _codes(proof)
    if established:
        detail = _score_window(evidence, proof, root, trial, workload, limits, execution, facts)
    else:
        detail = _score_ramp(evidence, proof, root, trial, workload, limits, execution, window)
    document.update(gates=detail['gates'], validity=detail['validity'], attribution=detail['attribution'], diagnostics=detail['diagnostics'], offered_load=detail.get('offered_load'), established=established)
    classification, reasons = detail['classification'], list(detail['reasons'])
    if infrastructure:
        classification, reasons = INFRASTRUCTURE_FAILURE, infrastructure + reasons
    elif refused:
        classification, reasons = INCONCLUSIVE, [item['code'] + ': ' + item['detail'] for item in refused] + reasons
    document.update(classification=classification, outcome=OUTCOME_OF[classification], reasons=reasons)
    return document


def _score_window(evidence, proof, root, trial, workload, limits, execution, facts):
    codes = set(_codes(proof))
    swarm = mw.load_swarm(root, trial, workload, limits, _sink())
    game = mw.load_game(root, _sink(), limits)
    game_rows = mw.load_sampler(root, 'game', _sink())
    exit_facts = game_exit(execution, game_rows)
    population = facts.get('population') if isinstance(facts.get('population'), dict) else None
    # A wall clock that stepped breaks every mapping across it, so an interval on the server's clock is no longer conservative. The swarm's own monotonic readings do not care.
    clock_broken = bool(codes & CLOCK_BREAKING_CODES)
    tick = _gate(UNKNOWN, why='a wall clock stepped, so no interval on the server\'s clock can be trusted') if clock_broken else tick_gate(game, population)
    if clock_broken:
        drops = _gate(UNKNOWN, why='a wall clock stepped, so no counter read can be placed against the window')
    else:
        drops = socket_gate(root, proof, limits) if isinstance(proof, dict) else _gate(UNKNOWN, why='no proof')
    departures = server_departures(game)
    if swarm is None:
        unknown = _gate(UNKNOWN, why='no interval to read')
        gates = dict(continuity=unknown, bot_errors=unknown, tick_budget=tick, game_socket_drops=drops, rtt_p95=unknown, enet_loss=unknown)
        validity = dict(verdict=NOT_PROVEN, offered_input=NOT_PROVEN, generator_sockets=NOT_PROVEN, independent_failures=[], unproven=['the swarm left no interval'])
        return dict(gates=gates, validity=validity, attribution=dict(game_exit=exit_facts, departures=[]), diagnostics=_diagnostics(facts, game_rows, game, None), classification=INCONCLUSIVE, reasons=['no scored interval exists on the swarm\'s record'])
    start, end = swarm['start'], swarm['end']
    interval_ns = swarm['controls'].get('input_interval_ns')
    interval_ns = interval_ns if mw.is_count(interval_ns) and interval_ns else 1
    rows, missing = bot_facts(swarm, departures, (lambda mono: None) if clock_broken else mapper(root, swarm, game), interval_ns, limits)
    expected = [bot for shard in swarm['shard_facts'] for bot in shard['expected']]
    shards_short = len(swarm['shard_facts']) != swarm['controls'].get('threads')
    samples, malformed = peer_samples(root, start, end)
    owed_until = {}
    for row in rows:
        lost = row.get('disconnect')
        owed_until[row['bot']] = trial['hold_s'] if lost is None else min(trial['hold_s'], max(0, (lost['observed_at_bot_mono_ns'] - start) // mw.NS + 1))
    for item in missing:
        owed_until[item['bot']] = trial['hold_s']
    rtt = rtt_gate(samples, expected, malformed) if expected and not shards_short else _gate(UNKNOWN, why='a shard file is missing')
    loss = loss_gate(samples, owed_until, start, trial['hold_s'], malformed) if owed_until and not shards_short else _gate(UNKNOWN, why='a shard file is missing', estimator=POLICY['enet_loss']['estimator'])
    core = (population or {}).get('core_game_mono_ns')
    departures_in_window = attribute(rows, departures, core, end, exit_facts.get('lost') and exit_facts.get('demonstrated'), tick['verdict'], drops['verdict'])
    continuity = _continuity_gate(rows, departures_in_window, exit_facts, population, codes, trial)
    bot_errors, independent = _error_gate(rows, missing)
    gates = dict(continuity=continuity, bot_errors=bot_errors, tick_budget=tick, game_socket_drops=drops, rtt_p95=rtt, enet_loss=loss)
    validity = _validity(proof, execution, facts, rows, missing, independent, shards_short)
    attribution = dict(game_exit=exit_facts, departures=departures_in_window, server_only_departures=sum(1 for item in departures_in_window if item['source'] == 'server_only'), input_missing_only_after_a_server_event=[row['bot'] for row in rows if row.get('input_missing_only_after_the_server_event')])
    offered = _offered_summary(rows, missing, trial)
    diagnostics = _diagnostics(facts, game_rows, game, swarm)
    classification, reasons = _decide(gates, validity, departures_in_window, exit_facts, codes, proof, execution, trial, swarm['window'].get('reason'))
    return dict(gates=gates, validity=validity, attribution=attribution, offered_load=offered, diagnostics=diagnostics, classification=classification, reasons=reasons)


def _continuity_gate(rows, departures, exit_facts, population, codes, trial):
    facts = dict(target=trial['target'], unexpected_disconnects_in_window=len(departures), game_process_ended_before_the_swarm=bool(exit_facts.get('lost')))
    if population:
        facts.update(ticks_in_interval=population.get('ticks_in_interval'), authenticated_transitions=population.get('authenticated_transitions'), disconnect_transitions=population.get('disconnect_transitions'))
    if departures or 'population_lost_in_window' in codes or exit_facts.get('lost'):
        return _gate(FAIL, **facts)
    late = [row['bot'] for row in rows if (row.get('disconnect') or {}).get('expected') is False]
    if late:
        return _gate(UNKNOWN, why='a bot lost its connection at the end of the window, and the clocks cannot place the server\'s side of it', bots=late[:10], **facts)
    if population is None or codes & CONTINUITY_UNKNOWN_CODES or 'server_refused_a_join' in codes:
        return _gate(UNKNOWN, why='no unbroken record of N authenticated across the interval', proof_reasons=sorted(codes & (CONTINUITY_UNKNOWN_CODES | {'server_refused_a_join'})), **facts)
    return _gate(PASS, **facts)


def _error_gate(rows, missing):
    """Zero bot errors, with each error sorted into what the disconnect itself accounts for and what it cannot."""
    independent = []
    totals = dict(errors=0, send_errors=0, panics=0, decode_failures=0, socket_send_errors=0, socket_zero_sends=0, socket_receive_errors=0)
    consequence = 0
    for row in rows:
        for key in totals:
            totals[key] += row[key]
        lost = row.get('disconnect')
        allowed = 1 if lost is not None and lost['expected'] is False else 0
        consequence += min(allowed, row['errors'])
        if row['errors'] > allowed or row['send_errors'] or row['panics']:
            independent.append(dict(bot=row['bot'], code='bot_errors', detail='errors %d send %d panics %d' % (row['errors'], row['send_errors'], row['panics'])))
        if lost is not None and lost['expected'] is True:
            independent.append(dict(bot=row['bot'], code='bot_quit_inside_the_window', detail='it asked to leave'))
    facts = dict(totals, errors_that_are_the_disconnect_itself=consequence, independent=len(independent), bots_without_a_frozen_row=[item['bot'] for item in missing][:10])
    if missing:
        verdict = FAIL if any(totals.values()) else UNKNOWN
    else:
        verdict = FAIL if any(totals.values()) else PASS
    return _gate(verdict, **facts), independent


def _validity(proof, execution, facts, rows, missing, independent, shards_short):
    """Offered load, on its own axis from the gates. Valid means proven; a value that is absent leaves it unproven and never valid."""
    codes = [code for code in _generator_reasons(proof) if code not in REDERIVED_GENERATOR_CODES]
    failures = [dict(code=code, source='window_proof') for code in codes]
    failures += [dict(code='swarm_execution', source='execution', detail=item) for item in (execution.get('problems') or {}).get('generator') or ()]
    failures += [dict(source='frozen_row', **item) for item in independent]
    below = [row['bot'] for row in rows if not row['input_floor_met']]
    failures += [dict(code='offered_input_below_minimum', source='frozen_row', bot=bot) for bot in below]
    decode = [row['bot'] for row in rows if row['decode_failures']]
    unproven = []
    if 'peer_sample_coverage' in _generator_reasons(proof):
        unproven.append('a bot has too few in-window ENet samples')
    if decode:
        unproven.append('bots %s failed to decode server packets: the server or the bot may have caused that' % decode[:10])
    if missing or shards_short:
        unproven.append('frozen rows missing: %s' % [item['bot'] for item in missing][:10])
    host = facts.get('bot_host') if isinstance(facts.get('bot_host'), dict) else None
    problems = facts.get('bot_host_problems') or []
    if host is None:
        sockets = NOT_PROVEN
        unproven.append('no bracketed collector rows for the bot host')
    elif 'generator_socket_drops' in problems:
        sockets = INVALID
    elif not mw.is_count(host.get('socket_drops_total')) or host.get('sockets_without_counters') or problems:
        sockets = NOT_PROVEN
        unproven.append('generator socket counters are not proven: %s' % problems)
    else:
        sockets = VALID
    if 'host_rebooted' in problems:
        unproven.append('the bot host rebooted')
    offered = INVALID if below else (NOT_PROVEN if missing or shards_short or decode else VALID)     # input counts stand apart from ENet sample coverage
    verdict = INVALID if failures else (NOT_PROVEN if unproven or offered != VALID or sockets != VALID else VALID)
    return dict(verdict=verdict, offered_input=offered, generator_sockets=sockets, generator_socket_drops=host.get('socket_drops_total') if host else None, independent_failures=failures, unproven=unproven)


def _offered_summary(rows, missing, trial):
    if not rows:
        return dict(bots=0, bots_expected=trial['target'], bots_without_a_frozen_row=[item['bot'] for item in missing][:10])
    worst = min(rows, key=lambda row: fractions.Fraction(row['sent'], row['scheduled']))
    return dict(bots=len(rows), bots_expected=trial['target'], scheduled_total=sum(row['scheduled'] for row in rows), sent_total=sum(row['sent'] for row in rows), worst_bot=worst['bot'], worst_ratio=worst['ratio'],
                bots_below_floor=[row['bot'] for row in rows if not row['input_floor_met']][:20], dead_frames_total=sum(row['dead_frames'] for row in rows), gap_max_ns=max(row['gap_max_ns'] for row in rows),
                bots_without_a_frozen_row=[item['bot'] for item in missing][:10], per_bot=rows)


def _decide(gates, validity, departures, exit_facts, codes, proof, execution, trial, swarm_reason=None):
    """Evidence integrity first, then the generator, then what the server is shown to have done. Only then can anything be a pass."""
    integrity = sorted(codes & INTEGRITY_CODES)
    if integrity:
        return INCONCLUSIVE, ['the evidence cannot be trusted: ' + ', '.join(integrity)]
    if swarm_reason == 'interrupted':
        return INCONCLUSIVE, ['the swarm was told to stop inside the window, so what it left says nothing about either side']
    if 'host_rebooted' in codes:
        return INFRASTRUCTURE_FAILURE, ['a host rebooted during the run']
    stop_requested = [item['bot'] for item in departures if item['cause'] == 'server_shutdown_request']
    other = [item['bot'] for item in departures if item['cause'] == 'reason_is_not_a_capacity_signal']
    unattributed = [item['bot'] for item in departures if item['cause'] == 'transport_timeout_unattributed']
    kicks = [item['bot'] for item in departures if item['cause'] == 'server_kick']
    distressed = [item['bot'] for item in departures if item['cause'] == 'transport_timeout_with_server_distress']
    demonstrated = []
    if exit_facts.get('lost') and exit_facts.get('demonstrated'):
        demonstrated.append('game process lost: %s (exit %s signal %s)' % (exit_facts['kind'], exit_facts.get('returncode'), exit_facts.get('signal')))
    if kicks:
        demonstrated.append('the server disconnected bots %s' % kicks[:10])
    if distressed:
        demonstrated.append('bots %s timed out while the server was failing' % distressed[:10])
    for name, label in (('tick_budget', 'Ticks over the literal 33.3 ms budget at 1 percent or more'), ('game_socket_drops', 'drops on the game socket inside the window'),
                        ('rtt_p95', 'pooled RTT p95 at or above 150 ms'), ('enet_loss', 'a second whose ENet loss estimate averaged 2 percent or more')):
        if gates[name]['verdict'] == FAIL:
            demonstrated.append(label)
    failures = validity['independent_failures']
    if failures:
        codes_seen = sorted({str(item.get('code')) for item in failures})
        if demonstrated or unattributed or stop_requested or other or exit_facts.get('lost'):
            return INCONCLUSIVE, ['both the generator and the server failed, and nothing separates them: ' + ', '.join(codes_seen) + '; ' + '; '.join(demonstrated + ['bots %s lost their connection' % (unattributed + stop_requested)[:10]])]
        return INVALID_LOAD, ['the generator failed on its own: ' + ', '.join(codes_seen)]
    if exit_facts.get('lost') and not exit_facts.get('demonstrated'):
        return INCONCLUSIVE, ['the game process ended and nothing on record says why: %s' % exit_facts.get('kind')]
    if stop_requested:
        return INCONCLUSIVE, ['the server was told to shut down inside the window, which is no capacity signal: bots %s' % stop_requested[:10]]
    if other:
        return INCONCLUSIVE, ['bots %s were refused for a reason that is no capacity signal' % other[:10]]
    if validity['verdict'] != VALID:
        return INCONCLUSIVE, ['offered load is not proven, so nothing about the server can stand on it: ' + '; '.join(validity['unproven'] or [validity['verdict']]) ]
    if demonstrated:
        return CAPACITY_FAILURE, demonstrated + (['bots %s also lost their connection with no cause on record' % unattributed[:10]] if unattributed else [])
    if unattributed:
        return INCONCLUSIVE, ['bots %s lost their connection by transport timeout, with the generator and the server both showing no failure: the cause is unknown' % unattributed[:10]]
    unknown = [name for name, gate in gates.items() if gate['verdict'] != PASS]
    if unknown:
        return INCONCLUSIVE, ['not proven: ' + '; '.join('%s (%s)' % (name, gates[name].get('why', gates[name]['verdict'])) for name in unknown)]
    if (proof or {}).get('status') != mw.COMPLETE:
        return INCONCLUSIVE, ['the common window is not proven: ' + ', '.join(sorted(codes))]
    problems = execution.get('problems') or {}
    if problems.get('game'):
        return INCONCLUSIVE, list(problems['game'])
    return VALID_PASS, ['every gate holds over a proven %d s common window at %d players' % (trial['hold_s'], trial['target'])]


def _diagnostics(facts, game_rows, game, swarm):
    """CPU, memory, gaps and the rest explain a result. No cutoff here is a gate, so a value in this block can never change a classification."""
    return dict(game_memory=memory_diagnostics(game_rows), game_host_kernel_counters=(facts.get('game_host') or {}).get('kernel_counters') if isinstance(facts.get('game_host'), dict) else None,
                bot_host_kernel_counters=(facts.get('bot_host') or {}).get('kernel_counters') if isinstance(facts.get('bot_host'), dict) else None,
                shard_max_poll_gap_ns=[shard.get('max_poll_gap_ns') for shard in facts.get('shards') or ()], clock_half_width_ms=(facts.get('clock') or {}).get('boundary_half_width_ms'),
                tick_rows=len(game['ticks']) if game else None, max_tick_gap_ns=(facts.get('population') or {}).get('max_tick_gap_ns') if isinstance(facts.get('population'), dict) else None)


# ---- a window that was never established --------------------------------------------------------------

def ramp_generator(root, trial, workload, limits):
    """Whether the swarm is shown healthy through a ramp that produced no window. A ramp failure can establish a failing bracket only over a generator proven valid."""
    invalid, unproven, integrity = [], [], []
    directory = root / 'bot' / 'swarm'
    swarm, problem = mw.load_json(directory / 'swarm.json')
    window, window_problem = mw.load_json(directory / 'window.json')
    if problem or window_problem:
        return dict(verdict=NOT_PROVEN, invalid=invalid, unproven=['swarm.json %s, window.json %s' % (problem, window_problem)], integrity=integrity, ports={})
    reasons = _sink()
    mw.check_producer(swarm, 'swarm.json', 'swarm.json', reasons)
    mw.check_producer(window, 'window.json', 'window.json', reasons)
    mw.check_build(swarm, reasons)
    controls = swarm.get('controls') or {}
    mw.check_controls(controls, trial, workload, reasons)
    integrity += [item['code'] for item in reasons.items]
    nonce = swarm.get('nonce')
    if window.get('nonce') != nonce:
        integrity.append('recorder_overwritten')
    if window.get('panicked_shards') or window.get('unjoined_shards'):
        invalid.append('a shard panicked or never finished: %s %s' % (window.get('panicked_shards'), window.get('unjoined_shards')))
    elif not isinstance(window.get('panicked_shards'), list) or not isinstance(window.get('unjoined_shards'), list):
        unproven.append('window.json does not say which shards ended')
    shards = controls.get('threads')
    if not mw.is_count(shards) or not shards:
        return dict(verdict=NOT_PROVEN, invalid=invalid, unproven=unproven + ['no shard count'], integrity=integrity, ports={})
    ports, ends, starvation = {}, [], limits['poll_starvation_ms'] * 1_000_000
    stagger = limits['stagger_tolerance_ms'] * 1_000_000
    for shard in range(shards):
        rows, problem = mw.load_ndjson(directory / ('shard-%d.ndjson' % shard))
        name = 'shard-%d' % shard
        if problem:
            unproven.append('%s %s' % (name, problem))
            continue
        local = _sink()
        if not mw.check_stream(rows, nonce, name, local) or not mw.check_producer(rows[0], name, 'shard-<k>.ndjson', local):
            bad = [item['code'] for item in local.items]
            (integrity if set(bad) & INTEGRITY_CODES else unproven).extend(bad)
            continue
        if ((rows[0].get('geometry') or {}).get('initialized_on_thread')) is not True:
            invalid.append(name + ' has no geometry')
        footer = rows[-1]
        if footer.get('left_early') is True:
            invalid.append(name + ' left early')
        elif footer.get('left_early') is not False:
            unproven.append(name + ' does not say whether it left early')
        gap = footer.get('max_poll_gap_ns')
        if not mw.is_count(gap):
            unproven.append(name + ' has no poll liveness')
        elif gap > starvation:
            invalid.append('%s did not poll for %.0f ms' % (name, gap / 1e6))
        fields = rows[0].get('bot_fields') or []
        latest = {}
        for row in rows:
            kind = row.get('k')
            if kind == 'join':
                if row.get('error'):
                    invalid.append('bot %s could not open its socket: %s' % (row.get('bot'), row.get('error')))
                elif not mw.is_int(row.get('scheduled_ns')) or not mw.is_int(row.get('actual_ns')):
                    unproven.append('bot %s has no join times' % row.get('bot'))
                elif row['actual_ns'] - row['scheduled_ns'] > stagger:
                    invalid.append('bot %s joined %.1f ms after its slot' % (row.get('bot'), (row['actual_ns'] - row['scheduled_ns']) / 1e6))
                if row.get('local_port') is not None:
                    ports[row.get('bot')] = row['local_port']
            elif kind == 'bot_end':
                ends.append(row)
                if row.get('panics'):
                    invalid.append('bot %s panicked' % row.get('bot'))
            elif kind in ('sample', 'drain_end'):
                for item in row.get('bots') or ():
                    if isinstance(item, list) and len(item) == len(fields):
                        latest[item[fields.index('id')]] = dict(zip(fields, item))
        for bot, item in latest.items():
            bad = {key: item.get(key) for key in ('send_errors', 'panics', 'socket_send_errors', 'socket_zero_sends', 'socket_receive_errors')}
            if any(not mw.is_count(value) for value in bad.values()):
                unproven.append('bot %s has no error counters' % bot)
            elif any(bad.values()):
                invalid.append('bot %s: %s' % (bot, {key: value for key, value in bad.items() if value}))
    bot_rows = mw.load_sampler(root, 'bot', _sink())
    series = mw.socket_series(bot_rows, 'bot')
    drops = 0
    for bot, port in sorted(ports.items()):
        readings = series.get(port) or []
        values = [item.get('drops') for item in readings]
        if len(values) < 2 or any(not mw.is_count(value) for value in values) or any(right < left for left, right in zip(values, values[1:])) or len({item.get('inode') for item in readings}) != 1:
            unproven.append('bot %s has no proven socket counter' % bot)
        else:
            drops += values[-1] - values[0]
    if not ports:
        unproven.append('no bot ever opened a socket')
    if drops:
        invalid.append('generator sockets dropped %d datagrams in the ramp' % drops)
    verdict = INVALID if invalid else (NOT_PROVEN if unproven or integrity else VALID)
    return dict(verdict=verdict, invalid=invalid[:20], unproven=unproven[:20], integrity=sorted(set(integrity)), ports=ports, ends=ends, reason=window.get('reason'), generator_socket_drops=drops if not unproven else None)


def ramp_overrun(game):
    """The literal gate over what the server did while it held anyone. The server's own clock, so nothing here depends on mapping a boundary."""
    if game is None:
        return _gate(UNKNOWN, why='the server left no complete Tick record')
    held = [tick for tick in game['ticks'] if tick[2] >= 1]
    if not held:
        return _gate(UNKNOWN, why='the server never held an authenticated player', ticks=0)
    over = sum(1 for tick in held if tick[3] > TICK_BUDGET_NS)
    facts = dict(budget_ns=TICK_BUDGET_NS, ticks=len(held), over=over, ratio=ratio(over, len(held)))
    return _gate(FAIL if over * 100 >= len(held) * TICK_OVER_PERCENT else PASS, **facts)


def _score_ramp(evidence, proof, root, trial, workload, limits, execution, window):
    """No common window exists, so nothing here can pass. It can still be a demonstrated failure, and it must not be called one from a timeout alone."""
    health = ramp_generator(root, trial, workload, limits)
    game = mw.load_game(root, _sink(), limits)
    game_rows = mw.load_sampler(root, 'game', _sink())
    exit_facts = game_exit(execution, game_rows)
    overrun = ramp_overrun(game)
    refused = [row for row in (game or {}).get('population') or () if row.get('k') in ('connect_rejected', 'auth_rejected')]
    kicks = sorted(row.get('bot') for row in health.get('ends') or () if isinstance(row.get('disconnected'), dict) and row['disconnected'].get('reason') == REASON_KICKED and row['disconnected'].get('expected') is False)
    reason = health.get('reason') or (window or {}).get('reason')
    unknown = _gate(UNKNOWN, why='no common window was established', swarm_reason=reason)
    gates = dict(continuity=_gate(FAIL if exit_facts.get('lost') or kicks else UNKNOWN, why='N never held: %s' % reason, target=trial['target']), bot_errors=unknown, tick_budget=dict(overrun, scope='every Tick with at least one authenticated player, the ramp and any drain'),
                 game_socket_drops=unknown, rtt_p95=unknown, enet_loss=unknown)
    execution_failures = list((execution.get('problems') or {}).get('generator') or ())
    validity = dict(verdict=health['verdict'], offered_input=NOT_PROVEN, generator_sockets=VALID if health.get('generator_socket_drops') == 0 else NOT_PROVEN, generator_socket_drops=health.get('generator_socket_drops'),
                    independent_failures=[dict(code='ramp', source='shard_files', detail=item) for item in health.get('invalid') or ()] + [dict(code='swarm_execution', source='execution', detail=item) for item in execution_failures], unproven=health.get('unproven') or [])
    if execution_failures and validity['verdict'] != INVALID:
        validity['verdict'] = INVALID
    demonstrated = []
    if exit_facts.get('lost') and exit_facts.get('demonstrated'):
        demonstrated.append('game process lost in the ramp: %s (exit %s signal %s)' % (exit_facts['kind'], exit_facts.get('returncode'), exit_facts.get('signal')))
    if kicks:
        demonstrated.append('the server disconnected authenticated bots %s in the ramp' % kicks[:10])
    if overrun['verdict'] == FAIL:
        demonstrated.append('Ticks over the literal 33.3 ms budget at 1 percent or more while the server held players')
    attribution = dict(game_exit=exit_facts, swarm_reason=reason, departures=[], refused_joins=len(refused), server_kicks=kicks)
    classification, reasons = _decide_ramp(health, validity, demonstrated, exit_facts, refused, reason)
    return dict(gates=gates, validity=validity, attribution=attribution, diagnostics=_diagnostics({}, game_rows, game, None), classification=classification, reasons=reasons)


def _decide_ramp(health, validity, demonstrated, exit_facts, refused, reason):
    if health.get('integrity'):
        return INCONCLUSIVE, ['the evidence cannot be trusted: ' + ', '.join(health['integrity'])]
    if reason == 'interrupted':
        return INCONCLUSIVE, ['the swarm was stopped before a window was established']
    if validity['verdict'] == INVALID or reason == 'shard_exited_before_window':
        problems = [item.get('detail') for item in validity['independent_failures']] or [str(reason)]
        if demonstrated:
            return INCONCLUSIVE, ['both the generator and the server failed in the ramp, and nothing separates them: ' + '; '.join(problems + demonstrated)]
        return INVALID_LOAD, ['the generator failed on its own in the ramp: ' + '; '.join(problems)]
    if validity['verdict'] != VALID:
        return INCONCLUSIVE, ['the ramp failed over a generator not proven valid: ' + '; '.join(validity['unproven'])]
    if exit_facts.get('lost') and not exit_facts.get('demonstrated'):
        return INCONCLUSIVE, ['the game process ended in the ramp and nothing on record says why: %s' % exit_facts.get('kind')]
    if refused:
        return INCONCLUSIVE, ['the server refused %d joins: a configured limit or a rejected ticket, which is no capacity signal' % len(refused)]
    if demonstrated:
        return CAPACITY_FAILURE, demonstrated
    return INCONCLUSIVE, ['the ramp ended (%s) with a valid generator and no failure on the server\'s record: a timeout alone is not a capacity limit' % reason]


# ---- the executor's seam ------------------------------------------------------------------------------

def score(evidence):
    """What ``run_executor`` calls. ``score`` in the answer is the document to retain, whose hash the executor makes the evidence reference."""
    document = evaluate(evidence)
    return dict(outcome=document['outcome'], evidence_ref=evidence.get('execution_ref'), scorer=SCORER, reasons=list(document['reasons']), generator_failure_attributed_to_server=document['outcome'] == search.FAIL, score=document)


def canonical(document):
    return json.dumps(document, indent=2, sort_keys=True) + '\n'


def load_retained(path):
    with contextlib.suppress(OSError, ValueError):
        document = json.loads(pathlib.Path(path).read_text())
        if isinstance(document, dict) and document.get('schema') == SCORE_SCHEMA:
            return document
    return None
