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

Whose evidence. A hash shows which bytes arrived, not whose they are. ``measurement_window`` holds every recorder to the identities the supervisors sealed, including for a ramp that never produced a window, and it names which
reasons come from the swarm's own files. All of those stand beside any server failure, because none of them can be the server's doing. A server's missing data can be the consequence of its demonstrated crash.

An exit. Only the supervisor's record of the exit proves anything. The host's OOM count cannot say who was killed or when: it stays a diagnostic. A SIGKILL is an out-of-memory kill of the game only with ``process_oom``'s proof, from the kernel's
count local to a cgroup leaf that holds only the supervised game. A count for the whole unit names nobody. Without all of that it stays unexplained.

Boundaries. A Tick or a counter read near an edge of a mapped interval may or may not belong to the window, so a verdict must hold for every position the clocks allow. Tick counts
and socket drops are evaluated at both extremes of that uncertainty, and anything that depends on where the window really was stays unknown.
"""
import ast
import contextlib
import fractions
import hashlib
import json
import math
import pathlib
import re

import do_session
import guest_runner
import measurement_window as mw
import search

SCORE_SCHEMA = 'omega.do-session.run-score/1'
CLASSIFICATION_SCHEMA = 'omega.do-session.run-classification/1'
SCORER = 'omega.do-session.capacity-scorer/1'
SCORE_FILE = 'score.json'
TERMINAL_FACT_SCHEMA = 'omega.do-session.run-terminal-fact/1'
TERMINAL_FACT_GLOB = 'terminal-fact-*.json'
TERMINAL_FACT_NAME = re.compile(r'terminal-fact-(\d{4,})-\d+\.json')
CORRUPT_OBSERVATION_SCHEMA = 'omega.do-session.corrupt-observation/1'
CORRUPT_OBSERVATION_GLOB = 'corrupt-observation-*.json'
CORRUPT_EVIDENCE_DIR = 'corrupt-evidence'
SEAL_RECEIPT_SCHEMA = 'omega.do-session.seal-receipt/1'
SEAL_RECEIPT_GLOB = 'seal-receipt-*.json'
VALIDATION_GUARD_SCHEMA = 'omega.do-session.validation-guard/1'
VALIDATION_GUARD_DIR = 'validation-guards'     # beside runs/ and never inside a run's directory, whose own sync is what it has to outlast
STOP_RECORD_WRITES = (TERMINAL_FACT_GLOB + do_session.WRITING + '*', CORRUPT_OBSERVATION_GLOB + do_session.WRITING + '*')
READ_FAILURES = (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError, ArithmeticError)     # whatever a file in a run directory turns out to hold, a reader answers
COUNT_LIMIT = 2 ** 63     # far past any count or reading here. JSON integers have no size of their own, so a reader needs one
GATE_NAMES = ('continuity', 'bot_errors', 'tick_budget', 'game_socket_drops', 'rtt_p95', 'enet_loss')
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
    generator_evidence='A failed gate or a crash establishes nothing over a generator not proven valid. Every reason the prover draws from the swarm\'s own files stands: a server\'s missing data can be the consequence of its demonstrated crash, and a generator\'s cannot.',
    ramp=dict(definition='A ramp can fail and can never pass. Its failure needs the supervised swarm and game identities, a kick only of a bot both sides recorded as authenticated, and zero generator socket drops proven on every opened socket by a counter read certainly after the abort. A read that may precede the abort, or a socket no such read saw, leaves the generator not proven.'),
    oom='The host-wide kernel OOM count is a diagnostic and never explains a process exit. A count for the run\'s unit names no process, because the kernel raises it before the SIGKILL and another member can be counted and still alive at any read, so it never explains a process exit either. A game SIGKILL is out_of_memory only when the kernel counted exactly one OOM kill local to a leaf cgroup of the run\'s unit, made fresh for the game before it started, holding the sealed game and nobody else at every read, between a baseline of zero and a read right after the reap. Anything less stays killed_with_no_cause_on_record.',
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
                        if not _is_real(rtt) or rtt < 0 or not mw.is_count(loss) or loss > LOSS_SCALE:
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


def _oom_reading(document, name):
    reading = document.get(name)
    return reading if isinstance(reading, dict) and mw.is_count(reading.get('oom_kill')) and mw.is_count(reading.get('mono_ns')) and isinstance(reading.get('procs'), list) else None


def process_oom(root, execution):
    """Whether the sealed evidence shows the kernel's OOM killer chose the game process. Returns (shown, facts), where ``facts`` always says why, and neither a host-wide count nor a count for the whole unit ever enters into it.

    The kernel raises its count against the cgroup of the process it chose, before it sends SIGKILL. In the unit's cgroup that names nobody, because another member can be counted and still be alive at any read. In a leaf holding only the game it names the game. So the proof
    is that leaf: made fresh by the supervisor, of the plan's own unit, holding the sealed game and nobody else at every read, with the supervisor and sampler in a leaf of their own, and the leaf's count rising by exactly one by the time the game was reaped.
    A file of this schema is what ``guest_runner.OomWatch`` writes, read after the same sealed hashes as every other run file.
    """
    root = pathlib.Path(root)
    role = ((execution or {}).get('roles') or {}).get('game') or {}
    identity = role.get('identity') or {}
    document, problem = mw.load_json(root / 'game' / guest_runner.OOM_EVIDENCE)
    if problem:
        return False, dict(status='missing', problems=['%s %s' % (guest_runner.OOM_EVIDENCE, problem)])
    if document.get('schema') != guest_runner.OOM_SCHEMA:
        return False, dict(status='refused', problems=['it is schema %r' % (document.get('schema'),)])
    if document.get('available') is not True:
        return False, dict(status='unavailable', problems=[str(document.get('unavailable'))])
    problems = []
    plan, plan_problem = mw.load_json(root / 'plan-game.json')
    if plan_problem:
        problems.append('no plan to hold its unit to: %s' % plan_problem)
    elif plan.get('unit_mode') != guest_runner.SYSTEMD or not plan.get('unit') or document.get('unit') != plan['unit']:
        problems.append('it is of unit %r, and the plan says %r in mode %r' % (document.get('unit'), plan.get('unit'), plan.get('unit_mode')))
    cgroup = document.get('cgroup')
    if not isinstance(cgroup, str) or pathlib.PurePosixPath(cgroup).name != document.get('unit'):
        problems.append('cgroup %r is not that unit\'s own' % (cgroup,))
    if (execution or {}).get('run_id', document.get('run_id')) != document.get('run_id') or document.get('role') != 'game':
        problems.append('it is of run %r role %r' % (document.get('run_id'), document.get('role')))
    processes = identity.get('processes') or {}
    expected = dict(processes, supervisor=identity.get('supervisor'))
    named = dict(document.get('processes') or {}, supervisor=document.get('supervisor'))
    keys = ('pid', 'start_id', 'boot_id')
    for name in ('game', 'sampler', 'supervisor'):
        want, have = expected.get(name), named.get(name)
        if not isinstance(want, dict) or not isinstance(have, dict) or any(not want.get(key) or want.get(key) != have.get(key) for key in keys):
            problems.append('%s is not the supervised process: %s, sealed %s' % (name, have, want))
    if set(named) != {'game', 'sampler', 'supervisor'}:
        problems.append('it names members %s' % sorted(named))
    if not identity.get('invocation_id') or document.get('invocation_id') != identity.get('invocation_id'):
        problems.append('it is of invocation %r, and the sealed one is %r' % (document.get('invocation_id'), identity.get('invocation_id')))
    leaf, supervision = document.get('leaf'), document.get('supervision')
    if not isinstance(cgroup, str) or leaf != cgroup + '/' + guest_runner.WORKLOAD_LEAF or supervision != cgroup + '/' + guest_runner.SUPERVISION_LEAF:
        problems.append('leaf %r and supervision %r are not the two leaves of that unit' % (leaf, supervision))
    if (document.get('member_cgroups') or {}) != dict(game=leaf, sampler=supervision, supervisor=supervision):
        problems.append('the game is not alone in its leaf: %s' % (document.get('member_cgroups'),))
    readings = [_oom_reading(document, name) for name in ('baseline', 'bound', 'primary_exit')]
    if any(reading is None for reading in readings):
        problems.append('a read of the leaf\'s counters is missing')
        return False, dict(status='not_attributable', problems=problems)
    baseline, bound, at_exit = readings
    final = _oom_reading(document, 'final')
    pid_of = lambda name: (named.get(name) or {}).get('pid')
    for name, reading, allowed in (('baseline', baseline, set()), ('bound', bound, {pid_of('game')}), ('primary_exit', at_exit, set())):
        if not set(reading['procs']) <= allowed:
            problems.append('at %s the leaf held %s, and may hold only the game while it lives' % (name, sorted(set(reading['procs']) - allowed)))
    if any(right['mono_ns'] <= left['mono_ns'] for left, right in zip(readings, readings[1:])):
        problems.append('its reads are out of order')
    series = [reading['oom_kill'] for reading in readings + ([final] if final else [])]
    if any(right < left for left, right in zip(series, series[1:])):
        return False, dict(status='not_attributable', problems=problems + ['the counter moved backward: %s' % series], counts=series)
    if baseline['oom_kill'] != 0:
        problems.append('a leaf made fresh for this run counts from zero, and this one began at %d' % baseline['oom_kill'])
    if document.get('final') is not None and final is None:
        problems.append('the last read is malformed')
    if final is not None and (final['oom_kill'] != at_exit['oom_kill'] or final['procs']):
        problems.append('with the game gone the leaf still changed: %d kills and %s by the last read' % (final['oom_kill'], final['procs']))
    delta = at_exit['oom_kill'] - baseline['oom_kill']
    facts = dict(source=document.get('source'), cgroup=cgroup, leaf=leaf, oom_kill_in_leaf=delta, unit_oom_kill_at_reap=at_exit.get('unit_oom_kill'), read_after_reap_ns=at_exit['mono_ns'])
    if delta != 1:
        problems.append('the kernel counted %d OOM kills in the game\'s own leaf before the reap, and one kill of the one process in it is what this can attribute' % delta)
    if (at_exit.get('oom_group_kill') or 0) != (baseline.get('oom_group_kill') or 0):
        problems.append('a group OOM kill is on record in the leaf')
    if at_exit.get('primary') != 'game' or at_exit.get('signal') != SIGKILL or at_exit.get('returncode') is not None:
        problems.append('what it read followed the exit %r signal %r of %r' % (at_exit.get('returncode'), at_exit.get('signal'), at_exit.get('primary')))
    return not problems, dict(facts, status='victim_matched' if not problems else 'not_attributable', problems=problems)


def game_exit(execution, sampler_rows, root):
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
        shown, oom = process_oom(root, execution)
        facts.update(host_oom_kill_delta=_counter_delta(_memory_values(sampler_rows, 'oom_kill')), process_oom=oom)
        return dict(facts, kind='out_of_memory', demonstrated=True) if shown else dict(facts, kind='killed_with_no_cause_on_record', demonstrated=False)
    return dict(facts, kind='ended_with_no_cause_on_record', demonstrated=False)


def _memory_values(rows, key):
    return [row['memory'][key] for row in rows if isinstance(row.get('memory'), dict) and mw.is_count(row['memory'].get(key))]


def _counter_delta(values):
    """First to last of a cumulative counter. One that moved backward was reset, so it says nothing."""
    if len(values) < 2 or any(right < left for left, right in zip(values, values[1:])):
        return None
    return values[-1] - values[0]


def memory_diagnostics(rows):
    """Memory pressure, which selects a conditional RAM tier and is no gate. Absent on a platform without it."""
    if not any(isinstance(row.get('memory'), dict) for row in rows):
        return None
    available = _memory_values(rows, 'MemAvailable')
    return dict(mem_available_min_bytes=min(available) if available else None, host_oom_kill_delta=_counter_delta(_memory_values(rows, 'oom_kill')), pgmajfault_delta=_counter_delta(_memory_values(rows, 'pgmajfault')), pswpout_delta=_counter_delta(_memory_values(rows, 'pswpout')))


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
    if proof.get('run_id') != evidence.get('run_id'):
        problems.append(dict(code='proof_is_of_another_trial', detail='the proof is of run %r' % (proof.get('run_id'),)))
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


def _reasons_of(proof):
    """A proof's reasons that are of a shape to read. Whether all of them are is ``proof_shape_problems``' to say."""
    reasons = proof.get('reasons') if isinstance(proof, dict) else None
    return [item for item in reasons if isinstance(item, dict) and isinstance(item.get('code'), str)] if isinstance(reasons, list) else []


def _codes(proof):
    return sorted({item['code'] for item in _reasons_of(proof)})


def _generator_reasons(proof):
    return sorted({item['code'] for item in _reasons_of(proof) if item.get('category') == mw.GENERATOR})


def proof_shape_problems(proof):
    """Whether a retained window proof has the shape its writer gives it, so that what it says can be read at all. Says nothing of whose it is."""
    if not isinstance(proof, dict):
        return ['it is not a JSON object']
    problems = []
    reasons = proof.get('reasons')
    if reasons is not None and (not isinstance(reasons, list) or len(_reasons_of(proof)) != len(reasons) or not all(isinstance(item.get('category'), (str, type(None))) for item in reasons)):
        problems.append('its reasons are of no known shape')
    if not isinstance(proof.get('facts'), (dict, type(None))):
        problems.append('its facts are of no known shape')
    if not isinstance(proof.get('status'), (str, type(None))):
        problems.append('its status is of no known shape')
    return problems


def execution_identities(execution):
    """Every process the supervisors named for this run, as the sealed record has them."""
    found = {}
    roles = execution.get('roles') if isinstance(execution, dict) else None
    for role, view in (roles.items() if isinstance(roles, dict) else ()):
        identity = view.get('identity') if isinstance(view, dict) else None
        processes = identity.get('processes') if isinstance(identity, dict) else None
        found[role] = {name: {key: item.get(key) if isinstance(item, dict) else None for key in ('pid', 'start_id', 'boot_id')} for name, item in sorted(processes.items())} if isinstance(processes, dict) else {}
    return found


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
                    inputs=dict(session_id=evidence.get('session_id'), manifest_sha256=evidence.get('manifest_sha256'), controller_sha=evidence.get('controller_sha'), identities=execution_identities(execution),
                                execution_sha256=evidence.get('execution_sha256'), window_proof_sha256=evidence.get('window_proof_sha256'), measurement_schema=(proof or {}).get('measurement_schema') if isinstance(proof, dict) else None,
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
    exit_facts = game_exit(execution, game_rows, root)
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


def _generator_evidence_missing(facts):
    """What the swarm's own files fail to show. No failed gate or crash can excuse any of it, because none of it can be the server's doing."""
    problems = facts.get('swarm_problems')
    if not isinstance(problems, list):
        return ['the proof does not say what the swarm\'s own files show']
    codes = sorted({item.get('code') for item in problems if isinstance(item, dict) and item.get('category') != mw.GENERATOR and item.get('code') not in INTEGRITY_CODES})
    found = ['necessary generator evidence is missing: ' + ', '.join(codes)] if codes else []
    if facts.get('swarm_wall_clock_steps'):
        found.append('the bot host\'s wall clock stepped, so its counter reads cannot be placed against the window')
    return found


def _validity(proof, execution, facts, rows, missing, independent, shards_short):
    """Offered load, on its own axis from the gates. Valid means proven; a value that is absent leaves it unproven and never valid."""
    codes = [code for code in _generator_reasons(proof) if code not in REDERIVED_GENERATOR_CODES]
    failures = [dict(code=code, source='window_proof') for code in codes]
    failures += [dict(code='swarm_execution', source='execution', detail=item) for item in (execution.get('problems') or {}).get('generator') or ()]
    failures += [dict(source='frozen_row', **item) for item in independent]
    below = [row['bot'] for row in rows if not row['input_floor_met']]
    failures += [dict(code='offered_input_below_minimum', source='frozen_row', bot=bot) for bot in below]
    decode = [row['bot'] for row in rows if row['decode_failures']]
    unproven = _generator_evidence_missing(facts)
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
        unproven.append('generator socket counters are not proven: %d of %d sockets have one, problems %s' % (host.get('sockets_with_counters') or 0, (host.get('sockets_with_counters') or 0) + (host.get('sockets_without_counters') or 0), problems))
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
        return INCONCLUSIVE, ['the game process ended and nothing on record says why: %s' % exit_facts.get('kind')] + (['on record beside it, and not separable from it: ' + '; '.join(demonstrated)] if demonstrated else [])
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

def ramp_generator(proof):
    """Whether the proof shows the swarm healthy through a ramp that produced no window. A ramp failure can establish a failing bracket only over a generator proven valid."""
    facts = (proof.get('facts') if isinstance(proof, dict) else None) or {}
    ramp = facts.get('ramp')
    integrity = sorted(set(_codes(proof)) & INTEGRITY_CODES)
    if not isinstance(ramp, dict):
        return dict(verdict=NOT_PROVEN, invalid=[], unproven=['the proof holds no account of this ramp'], integrity=integrity, ends=[], reason=None, generator_socket_drops=None)
    problems = [item for item in facts.get('swarm_problems') or () if isinstance(item, dict)]
    invalid = [item.get('detail') or item.get('code') for item in problems if item.get('category') == mw.GENERATOR and item.get('code') != 'window_not_established']
    unproven = [item.get('detail') or item.get('code') for item in problems if item.get('category') != mw.GENERATOR and item.get('code') not in INTEGRITY_CODES]
    host = ramp.get('bot_host') if isinstance(ramp.get('bot_host'), dict) else None
    if host is None:
        unproven.append('no bot collector rows cover this ramp')
    elif host.get('sockets_without_counters') or not mw.is_count(host.get('socket_drops_total')):
        unproven.append('generator socket counters are not proven: %d of the opened sockets have one, none for bots %s' % (host.get('sockets_with_counters') or 0, host.get('bots_without_counters')))
    drops = host.get('socket_drops_total') if host else None
    verdict = INVALID if invalid else (NOT_PROVEN if unproven or integrity else VALID)
    return dict(verdict=verdict, invalid=invalid[:20], unproven=unproven[:20], integrity=integrity, ends=ramp.get('ends') or [], reason=ramp.get('reason'), generator_socket_drops=drops if not unproven else None)


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
    health = ramp_generator(proof)
    game = mw.load_game(root, _sink(), limits)
    game_rows = mw.load_sampler(root, 'game', _sink())
    exit_facts = game_exit(execution, game_rows, root)
    overrun = ramp_overrun(game)
    refused = [row for row in (game or {}).get('population') or () if row.get('k') in ('connect_rejected', 'auth_rejected')]
    # The server also sends this reason to a join it refuses, so a kick needs a bot both sides recorded as authenticated.
    authenticated = {row.get('name') for row in game['population'] if row.get('k') == 'auth'} if game is not None else None
    kicks = sorted(row['bot'] for row in health.get('ends') or () if isinstance(row.get('disconnected'), dict) and row['disconnected'].get('reason') == REASON_KICKED and row['disconnected'].get('expected') is False
                   and row.get('authenticated') is True and (authenticated is None or 'LoadBot%03d' % row['bot'] in authenticated))
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
    classification, reasons = _decide_ramp(health, validity, demonstrated, exit_facts, refused, reason, _codes(proof))
    ramp_facts = (proof.get('facts') if isinstance(proof, dict) else None) or {}
    return dict(gates=gates, validity=validity, attribution=attribution, diagnostics=_diagnostics(dict(bot_host=(ramp_facts.get('ramp') or {}).get('bot_host')), game_rows, game, None), classification=classification, reasons=reasons)


def _decide_ramp(health, validity, demonstrated, exit_facts, refused, reason, codes):
    if health.get('integrity'):
        return INCONCLUSIVE, ['the evidence cannot be trusted: ' + ', '.join(health['integrity'])]
    if 'host_rebooted' in codes:
        return INFRASTRUCTURE_FAILURE, ['a host rebooted during the run']
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
        return INCONCLUSIVE, ['the game process ended in the ramp and nothing on record says why: %s' % exit_facts.get('kind')] + (['on record beside it, and not separable from it: ' + '; '.join(demonstrated)] if demonstrated else [])
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


# ---- what a retained decision must be bound to ---------------------------------------------------------

# A file's own hash says what its bytes are, not whose they are. These hold a retained score and classification to the run, session, policy, proof and execution they claim. They read files and
# recompute nothing, and a mismatch is refused: no expected hash is ever replaced by the hash of whatever is there now.

_ACCOUNT_OF_OBSERVATION = re.compile(r'^(?P<role>game|bot) (?P<path>.+) failed its hash: expected (?P<expected>[0-9a-f]{64}), found (?P<actual>[0-9a-f]{64}), kept at (?P<kept>.+)$')
_ACCOUNT_OF_EXPORT = re.compile(r'^(?P<role>game|bot) evidence was not fully exported: (?P<failed>\[.*\])$', re.DOTALL)
_REFERENCE = re.compile(r'^runs/(?P<run_id>[^/#]+)/(?P<name>[^/#]+)#sha256:(?P<sha256>[0-9a-f]{64})$')


def parse_reference(reference):
    """(run_id, file name, sha256) of a retained-file reference, or None."""
    match = _REFERENCE.match(reference) if isinstance(reference, str) else None
    return match.groups() if match else None


def file_sha256(path):
    try:
        return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def seal(document):
    """The document with a digest of its own content. It catches a score changed in place or cut short. It is no defence against someone deliberately rewriting session files, which is no threat these files answer."""
    body = {key: value for key, value in document.items() if key != 'document_sha256'}
    return dict(body, document_sha256=hashlib.sha256(canonical(body).encode('utf-8')).hexdigest())


def retained_expectation(run_dir, trial, session_id, manifest_sha256, controller_sha):
    """What this run's retained files must agree with, from what is already on record."""
    run_dir = pathlib.Path(run_dir)
    executions = {}
    for path in sorted(run_dir.glob('execution*.json')):
        record, problem = mw.load_json(path)
        if not problem:
            executions[file_sha256(path)] = record
    proof, problem = mw.load_json(run_dir / 'window-proof.json')
    return dict(run_dir=run_dir, run_id=trial['run_id'], trial={key: trial.get(key) for key in ('ordinal', 'phase', 'target', 'repetition', 'hold_s')}, session_id=session_id, manifest_sha256=manifest_sha256, controller_sha=controller_sha,
                executions=executions, proof=None if problem else proof, proof_sha256=None if problem else file_sha256(run_dir / 'window-proof.json'))


def _is_real(value):
    """A finite number of a size a reading here could have. An integer is judged as the integer it is: ``math.isfinite`` would first convert it to a float, and one too large for that raises."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return abs(value) < COUNT_LIMIT
    return isinstance(value, float) and math.isfinite(value)


def _is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < COUNT_LIMIT


def _is_ratio(value):
    """Nothing to say, or what ``exact`` writes: a fraction of counts as text, with its float beside it. No gate has a negative one."""
    if value is None or value == {}:
        return True
    return isinstance(value, dict) and isinstance(value.get('exact'), str) and re.fullmatch(r'\d+/[1-9]\d*', value['exact']) is not None and _is_real(value.get('approximate')) and value['approximate'] >= 0


def _gate_shape_problems(name, gate):
    """What the report reads out of one gate. A gate says only what its branch of the scorer found, so each field is held to its shape when it is there, and the fields that come with it have to be there too."""
    ratios, counts, readings = [], [], []
    if name == 'tick_budget':
        if 'ticks_wide' in gate and 'worst_possible_ratio' in gate:
            ratios += [gate.get('worst_possible_ratio'), gate.get('least_possible_ratio')]
            counts += [gate.get(key) for key in ('ticks_wide', 'ticks_narrow', 'over_wide', 'over_narrow')]
        if 'ticks' in gate:
            ratios.append(gate.get('ratio'))
            counts += [gate.get('ticks'), gate.get('over')]
    elif name == 'rtt_p95' and 'p95_ms' in gate:
        counts += [gate.get(key) for key in ('rank', 'samples')]
        readings += [gate.get(key) for key in ('p95_ms', 'max_ms')]
    elif name == 'enet_loss' and 'per_second_mean_peak' in gate:
        peak = gate['per_second_mean_peak']
        if not isinstance(peak, dict):
            return ['its %s gate has no peak of any known shape' % name]
        ratios += [peak.get('ratio'), gate.get('window_mean_of_seconds')]
        counts += [peak.get('second')] + [gate.get(key) for key in ('seconds_evaluated', 'seconds', 'borrowed_readings')]
    elif name == 'game_socket_drops' and 'drops_in_widest_interval' in gate:
        counts += [gate['drops_in_widest_interval'], gate.get('drops_proven_inside', 0)]
    elif name == 'bot_errors' and 'errors' in gate:
        counts += [gate.get(key) for key in ('errors', 'errors_that_are_the_disconnect_itself', 'independent')]
    if not all(_is_ratio(item) for item in ratios) or not all(_is_count(item) for item in counts) or not all(_is_real(item) and item >= 0 for item in readings) or not isinstance(gate.get('why', ''), str):
        return ['its %s gate is of no known shape' % name]
    if name == 'rtt_p95' and 'p95_ms' in gate and not 1 <= gate['rank'] <= gate['samples']:
        return ['its %s gate puts rank %d among %d samples' % (name, gate['rank'], gate['samples'])]
    return []


def _departure_problems(attribution):
    departures = attribution.get('departures')
    if departures is not None and (not isinstance(departures, list) or not all(isinstance(item, dict) and all(key in item for key in ('bot', 'cause', 'reason', 'server_reason', 'order', 'observation_lag_ns')) for item in departures)):
        return ['its departures are of no known shape']
    return []


def _score_shape_problems(document):
    """Whether a retained score has the shape its writer gives it, for everything anyone reads back out of it. A score carries its own digest, which only says it was not changed afterwards, so this is checked before any lookup or iteration, here rather than where each reader would trip on it."""
    problems = []
    gates, validity, attribution, inputs, offered = (document.get(key) for key in ('gates', 'validity', 'attribution', 'inputs', 'offered_load'))
    if isinstance(gates, dict):
        for name, gate in gates.items():
            if isinstance(gate, dict):
                problems += _gate_shape_problems(name, gate)
    if not isinstance(attribution, dict):
        problems.append('its attribution is of no known shape')
    else:
        problems += _departure_problems(attribution)
        if not isinstance(attribution.get('game_exit'), (dict, type(None))):
            problems.append('what it says of the game process is of no known shape')
    if not isinstance(inputs, dict):
        problems.append('its inputs are of no known shape')
    if isinstance(validity, dict) and ('offered_input' not in validity or 'generator_sockets' not in validity or not isinstance(validity.get('unproven'), (list, type(None))) or not isinstance(validity.get('independent_failures'), (list, type(None))) or not all(isinstance(item, dict) for item in validity.get('independent_failures') or ())):
        problems.append('its offered-load verdict is of no known shape')
    if not isinstance(offered, (dict, type(None))) or (offered and offered.get('bots') and (not all(key in offered for key in ('sent_total', 'scheduled_total', 'worst_bot')) or not _is_count(offered['sent_total']) or not _is_count(offered['scheduled_total']) or not _is_ratio(offered.get('worst_ratio')))):
        problems.append('its offered load is of no known shape')
    return problems


def _result_problems(document):
    """Whether this document's own result can be what it says. No decision is recomputed here: each classification simply needs the facts it stands on to be in the document."""
    problems = []
    classification, gates, validity = document.get('classification'), document.get('gates'), document.get('validity')
    if not isinstance(classification, str) or classification not in OUTCOME_OF:
        return ['it has the classification %r' % (classification,)]
    shape = _score_shape_problems(document)
    if shape:
        return shape
    if document.get('outcome') != OUTCOME_OF[classification]:
        problems.append('its outcome %r is not what %s means' % (document.get('outcome'), classification))
    if document.get('establishes_capacity') is not False:
        problems.append('one run claims to establish capacity')
    if not isinstance(gates, dict) or set(gates) != set(GATE_NAMES) or any(not isinstance(gate, dict) or gate.get('verdict') not in (PASS, FAIL, UNKNOWN) for gate in gates.values()):
        return problems + ['its gates are not the six accepted gates']
    if not isinstance(validity, dict) or validity.get('verdict') not in (VALID, INVALID, NOT_PROVEN):
        return problems + ['it has no offered-load verdict']
    if not isinstance(document.get('reasons'), list) or not document['reasons'] or not all(isinstance(reason, str) for reason in document['reasons']):
        problems.append('it gives no reasons')
    inputs = document.get('inputs') if isinstance(document.get('inputs'), dict) else {}
    attribution = document.get('attribution') if isinstance(document.get('attribution'), dict) else {}
    if classification == VALID_PASS:
        if {gate['verdict'] for gate in gates.values()} != {PASS} or validity['verdict'] != VALID or document.get('established') is not True or inputs.get('proof_status') != mw.COMPLETE or inputs.get('proof_reasons') or inputs.get('inadmissible'):
            problems.append('it says valid_pass and its gates, offered load or proof do not')
    elif classification == CAPACITY_FAILURE:
        exit_facts = attribution.get('game_exit') if isinstance(attribution.get('game_exit'), dict) else {}
        shown = any(gate['verdict'] == FAIL for gate in gates.values()) or exit_facts.get('demonstrated') is True or attribution.get('server_kicks') or any(item.get('cause') == 'server_kick' for item in attribution.get('departures') or ())
        if not shown or validity['verdict'] != VALID or inputs.get('inadmissible'):
            problems.append('it says capacity_failure and shows no demonstrated failure over a proven generator')
    elif classification == INVALID_LOAD:
        if validity['verdict'] != INVALID or inputs.get('inadmissible'):
            problems.append('it says invalid_offered_load and its offered load does not')
    return problems


def _binding_problems(document, expected):
    problems = []
    inputs = document.get('inputs') if isinstance(document.get('inputs'), dict) else {}
    if document.get('schema') != SCORE_SCHEMA or document.get('scorer') != SCORER:
        problems.append('it is schema %r from scorer %r' % (document.get('schema'), document.get('scorer')))
    if document.get('policy_sha256') != POLICY_SHA256 or document.get('policy') != POLICY:
        problems.append('it was made under policy %r, and this controller holds %s' % (document.get('policy_sha256'), POLICY_SHA256))
    if document.get('run_id') != expected['run_id']:
        problems.append('it is of run %r' % (document.get('run_id'),))
    if document.get('trial') != expected['trial']:
        problems.append('it is of trial %r' % (document.get('trial'),))
    for key in ('session_id', 'manifest_sha256', 'controller_sha'):
        if inputs.get(key) != expected[key]:
            problems.append('its %s is %r, and this session has %r' % (key, inputs.get(key), expected[key]))
    frozen = mw.schema()['id'], mw.schema_sha256()
    if (inputs.get('measurement_schema'), inputs.get('measurement_schema_sha256')) != frozen:
        problems.append('it was made under measurement schema %r' % (inputs.get('measurement_schema'),))
    proof = expected['proof']
    if proof is None or inputs.get('window_proof_sha256') != expected['proof_sha256']:
        problems.append('its window proof %r is not the retained one' % (inputs.get('window_proof_sha256'),))
    elif proof_shape_problems(proof):
        problems += ['its window proof: ' + item for item in proof_shape_problems(proof)]
    elif proof.get('run_id') != expected['run_id'] or inputs.get('proof_status') != proof.get('status') or inputs.get('proof_reasons') != _codes(proof):
        problems.append('what it says of the proof disagrees with the retained proof')
    execution = expected['executions'].get(inputs['execution_sha256']) if isinstance(inputs.get('execution_sha256'), str) else None
    if execution is None:
        problems.append('its execution record %r is not one retained for this run' % (inputs.get('execution_sha256'),))
    elif execution_record_problems(execution):
        problems += ['its execution record: ' + item for item in execution_record_problems(execution)]
    else:
        if execution.get('run_id') != expected['run_id'] or execution.get('session_id') != expected['session_id'] or execution.get('manifest_sha256') != expected['manifest_sha256']:
            problems.append('its execution record belongs to another run')
        if inputs.get('identities') != execution_identities(execution):
            problems.append('the process identities it names are not the sealed ones')
        if (execution.get('problems') or {}).get('infrastructure') and document.get('classification') != INFRASTRUCTURE_FAILURE:
            problems.append('its execution record shows an infrastructure failure, and it says %s' % document.get('classification'))
    return problems


def is_digest(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _fence_problems(token, expected):
    """A controller older than this run's dispatch knows nothing about it, and one newer than this session's fence does not exist."""
    if isinstance(token, bool) or not isinstance(token, int) or token < 1:
        return ['its fencing token is %r' % (token,)]
    problems = []
    if expected.get('dispatch_token') is not None and token < expected['dispatch_token']:
        problems.append('its fencing token %d is older than the token %d this run was dispatched under' % (token, expected['dispatch_token']))
    if expected.get('current_token') is not None and token > expected['current_token']:
        problems.append('its fencing token %d is newer than this session\'s %d' % (token, expected['current_token']))
    return problems


def _identity_problems(record, expected):
    return ['its %s is %r, and this run\'s is %r' % (key, record.get(key), expected[key]) for key in ('session_id', 'manifest_sha256', 'run_id') if record.get(key) != expected[key]]


def _terminal_fact_problems(path, record, expected):
    """Why a terminal-fact file cannot be this run's own. It is only ever believed for this session, this manifest, this run and a role of it, with the shape its writer gives it."""
    if not isinstance(record, dict) or record.get('schema') != TERMINAL_FACT_SCHEMA:
        return ['it is not a terminal fact of schema %s' % TERMINAL_FACT_SCHEMA]
    problems = _identity_problems(record, expected)
    if record.get('role') not in ('game', 'bot'):
        problems.append('it names role %r' % (record.get('role'),))
    if not _stops(record.get('outcome')):
        problems.append('it names outcome %r, which stops nothing' % (record.get('outcome'),))
    if not _all_reasons(record.get('details')):
        problems.append('it states no reason')
    if not isinstance(record.get('found_at'), str) or not record['found_at'].strip():
        problems.append('it does not say when it was found')
    token = record.get('fencing_token')
    problems += _fence_problems(token, expected)
    if isinstance(token, int) and not isinstance(token, bool) and token >= 1:
        named = TERMINAL_FACT_NAME.fullmatch(path.name)
        if named is None or int(named.group(1)) != token:
            problems.append('its name %s does not carry its fencing token %d' % (path.name, token))
    problems += _receipt_problems(path.parent, record.get('receipts'))
    if problems:
        return problems
    return _claim_problems(path.parent, [(record['role'], item) for item in record.get('receipts') or ()], record['details'], token, expected)


def _stops(outcome):
    return isinstance(outcome, str) and outcome in search.STOPPING


def _all_reasons(items):
    return isinstance(items, list) and bool(items) and all(isinstance(item, str) and item.strip() for item in items)


def _safe_inside(name):
    """A relative path that stays where it is put. The bytes behind it are for a run directory to answer, not for a reader to go looking for elsewhere."""
    if not isinstance(name, str) or not name or '\0' in name:
        return False
    pure = pathlib.PurePosixPath(name)
    return not pure.is_absolute() and '..' not in pure.parts


def _receipt_problems(run_dir, receipts):
    """A receipt is what a digest mismatch left. Optional for a fact with no bytes to name, and when present every hash in it has to hold."""
    if receipts is None:
        return []
    if not isinstance(receipts, list) or not all(isinstance(item, dict) for item in receipts):
        return ['its receipts are malformed']
    problems = []
    for item in receipts:
        expected_digest, actual_digest = item.get('expected_sha256'), item.get('actual_sha256')
        if not is_digest(expected_digest) or not is_digest(actual_digest) or expected_digest == actual_digest:
            problems.append('its receipt for %r does not hold two different hashes' % (item.get('path'),))
            continue
        retained = item.get('retained_as')
        if retained is None:
            continue
        if not _safe_inside(retained) or file_sha256(run_dir / retained) != actual_digest:
            problems.append('the bytes its receipt names at %r are not the bytes it hashed' % (retained,))
    return problems


def corrupt_evidence_name(role, relative, actual):
    """Where a file that failed its hash is kept: a name no transfer writes to, keyed by what was found, so a repeated sweep over the same bytes keeps one copy."""
    return '%s/%s/%s.%s' % (CORRUPT_EVIDENCE_DIR, role, relative.replace('/', '__'), actual)


def corrupt_observation_name(token, role, relative, actual):
    key = hashlib.sha256('\0'.join((role, relative, actual)).encode('utf-8')).hexdigest()[:16]
    return 'corrupt-observation-%04d-%s.json' % (token, key)


def corrupt_observation(session_id, manifest_sha256, run_id, role, relative, expected_digest, actual, token, found_at):
    """What a controller writes down the moment bytes fail their hash, before it keeps them and before any fact or registry word. See ``_corrupt_receipt``."""
    return dict(schema=CORRUPT_OBSERVATION_SCHEMA, session_id=session_id, manifest_sha256=manifest_sha256, run_id=run_id, role=role, path=relative, reason='hash mismatch', expected_sha256=expected_digest, actual_sha256=actual,
                retained_as=corrupt_evidence_name(role, relative, actual), fencing_token=token, found_at=found_at)


def _observation_problems(path, record, expected):
    """Why a corrupt observation cannot be this run's own. The same safeguards as a terminal fact, and its name, its retained name and the expected hash must follow from what it says."""
    if not isinstance(record, dict) or record.get('schema') != CORRUPT_OBSERVATION_SCHEMA:
        return ['it is not a corrupt observation of schema %s' % CORRUPT_OBSERVATION_SCHEMA]
    problems = _identity_problems(record, expected)
    role, relative, expected_digest, actual, token = record.get('role'), record.get('path'), record.get('expected_sha256'), record.get('actual_sha256'), record.get('fencing_token')
    if role not in ('game', 'bot'):
        problems.append('it names role %r' % (role,))
    if not _safe_inside(relative):
        problems.append('it names path %r' % (relative,))
    if not is_digest(expected_digest) or not is_digest(actual) or expected_digest == actual:
        problems.append('it does not hold two different hashes')
    if not isinstance(record.get('found_at'), str) or not record['found_at'].strip():
        problems.append('it does not say when it was found')
    fence = _fence_problems(token, expected)
    problems += fence
    if problems:
        return problems
    if path.name != corrupt_observation_name(token, role, relative, actual):
        problems.append('its name %s does not follow from what it says' % path.name)
    if record.get('retained_as') != corrupt_evidence_name(role, relative, actual):
        problems.append('it names bytes at %r, which is not where they are kept' % (record.get('retained_as'),))
    return problems + _corroboration_problems(path.parent, record, expected)


def seal_inventory(seal, run_id, role):
    """What a sealed document lists, as ``(path, sha256)`` pairs in a plain form, or None when it is of no shape or of another run. A receipt carries only what an observation is held to."""
    if not isinstance(seal, dict) or seal.get('run_id') != run_id or seal.get('role') != role or not isinstance(seal.get('files'), list):
        return None
    if not all(isinstance(item, dict) and _safe_inside(item.get('path')) and is_digest(item.get('sha256')) for item in seal['files']):
        return None
    return [dict(path=item['path'], sha256=item['sha256']) for item in seal['files']]


def seal_receipt_name(token, role, seal_sha256, files):
    """Keyed by what it says, so the same reply read twice keeps one file, and a status reply and the seal it named keep two."""
    key = hashlib.sha256(canonical(dict(seal_sha256=seal_sha256, files=files)).encode('utf-8')).hexdigest()[:16]
    return 'seal-receipt-%04d-%s-%s.json' % (token, role, key)


def seal_receipt(session_id, manifest_sha256, run_id, role, seal_sha256, files, token, found_at):
    """What a guest's own reply said this role sealed, written down before any file of it is judged. ``files`` is None for a reply that named only the digest."""
    return dict(schema=SEAL_RECEIPT_SCHEMA, session_id=session_id, manifest_sha256=manifest_sha256, run_id=run_id, role=role, seal_sha256=seal_sha256, files=files, fencing_token=token, found_at=found_at)


def _seal_receipt_problems(path, record, expected):
    """Why a seal receipt cannot be this run's own."""
    if not isinstance(record, dict) or record.get('schema') != SEAL_RECEIPT_SCHEMA:
        return ['it is not a seal receipt of schema %s' % SEAL_RECEIPT_SCHEMA]
    problems = _identity_problems(record, expected)
    role, digest, files, token = record.get('role'), record.get('seal_sha256'), record.get('files'), record.get('fencing_token')
    if role not in ('game', 'bot'):
        problems.append('it names role %r' % (role,))
    if not is_digest(digest):
        problems.append('it holds no seal digest')
    if files is not None and seal_inventory(dict(run_id=expected['run_id'], role=role, files=files), expected['run_id'], role) != files:
        problems.append('its inventory is of no known shape')
    problems += _fence_problems(token, expected)
    if not problems and path.name != seal_receipt_name(token, role, digest, files):
        problems.append('its name %s does not follow from what it says' % path.name)
    return problems


def _seal_receipts(run_dir, role, token, expected):
    """(this role's receipts no newer than ``token``, problems). A receipt newer than what it would vouch for came too late to say what that controller expected, and a receipt that cannot be held to this run taints all of them."""
    receipts, problems = [], []
    for path in sorted(run_dir.glob(SEAL_RECEIPT_GLOB)):
        record, problem = mw.load_json(path)
        found = [problem] if problem else _seal_receipt_problems(path, record, expected)
        if found:
            problems.append('the seal receipt %s cannot be held to this run: %s' % (path.name, '; '.join(found)))
        elif record['role'] == role and record['fencing_token'] <= token:
            receipts.append(record)
    return receipts, problems


def _execution_seal_problems(run_dir, role, sealed, expected):
    """(problems, exported): what this run's own execution records say of the seal, and whether one says it reached this disk. A record that cannot be held to this run says nothing here, and ``stop_records`` already refuses over it."""
    problems, exported = [], False
    for path in sorted(run_dir.glob('execution*.json')):
        record, problem = mw.load_json(path)
        if problem or execution_record_problems(record) or _identity_problems(record, expected):
            continue
        roles = record.get('roles') if isinstance(record.get('roles'), dict) else {}
        view = roles.get(role) if isinstance(roles.get(role), dict) else {}
        digest = view.get('seal_sha256')
        if digest is not None and digest != sealed:
            problems.append('the sealed execution record %s says the seal was %r, and the retained seal receipts say %s' % (path.name, digest, sealed))
        views = record.get('exported') if isinstance(record.get('exported'), dict) else {}
        failed = views.get(role).get('failed') if isinstance(views.get(role), dict) else None
        if isinstance(failed, list) and not any(isinstance(item, dict) and item.get('path') == guest_runner.SEAL for item in failed):
            exported = True
    return problems, exported


def _retained_seal_problems(run_dir, role, relative, expected_digest, sealed, exported, expected):
    """The role's own seal file against the receipts, when it is here. It is the last file a transfer brings, so a crash can leave it not yet arrived, and only a record that says it did arrive makes its absence a problem."""
    path = run_dir / role / guest_runner.SEAL
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        # What is said of the seal itself has already been held to the receipts: a seal lost here and then fetched back wrong leaves exactly this.
        return ['the sealed execution record says the seal arrived, and it is gone'] if exported and relative != guest_runner.SEAL else []
    except OSError as error:
        return ['the retained seal could not be read: ' + type(error).__name__]
    if hashlib.sha256(data).hexdigest() != sealed:
        return ['the retained seal is not the one its receipts name']
    seal, problem = mw.load_json(path)
    files = None if problem else seal_inventory(seal, expected['run_id'], role)
    if files is None:
        return ['the retained seal cannot be held to this run and role']
    if relative != guest_runner.SEAL and dict(path=relative, sha256=expected_digest) not in files:
        return ['the retained seal does not list %s at %s' % (relative, expected_digest)]
    return []


def _corroboration_problems(run_dir, record, expected):
    """Whether something older than this observation says what it says it expected. Its name and its retained hash only prove which bytes it has: without this, its expected hash would be nothing but its own word, and a good file could be labelled corrupt for good.

    The receipt is retained before any transfer that could produce an observation, so a genuine one finds it after any crash, and nothing here recomputes or replaces an expected hash. Whatever is missing, unreadable, changed or of another role leaves an unverified record, never a fact.
    """
    role, relative, expected_digest = record['role'], record['path'], record['expected_sha256']
    receipts, problems = _seal_receipts(run_dir, role, record['fencing_token'], expected)
    if problems:
        return problems
    if not receipts:
        return ['nothing retained before it says what %s sealed, so the hash it expected is only its own word' % role]
    seals = sorted({item['seal_sha256'] for item in receipts})
    if len(seals) != 1:
        return ['the retained seal receipts of %s disagree: %s' % (role, ', '.join(seals))]
    sealed = seals[0]
    if relative == guest_runner.SEAL:
        if expected_digest != sealed:
            return ['it expected %s of the seal, and the retained seal receipts say %s' % (expected_digest, sealed)]
    else:
        inventories = [item['files'] for item in receipts if item['files'] is not None]
        if not inventories:
            return ['no retained seal receipt lists what %s sealed, so nothing says %s was among it' % (role, relative)]
        if any(dict(path=relative, sha256=expected_digest) not in files for files in inventories):
            return ['the retained seal receipts do not list %s at %s' % (relative, expected_digest)]
    problems, exported = _execution_seal_problems(run_dir, role, sealed, expected)
    return problems + _retained_seal_problems(run_dir, role, relative, expected_digest, sealed, exported, expected)


def _tells_of_corrupt_bytes(text):
    """Whether a reason is an account of bytes failing their hash, in the words its writers use: a receipt's own reason, or an observation's."""
    return 'failed its hash' in text or 'hash mismatch' in text


def _receipts_told_in(text):
    """The receipts a corruption account spells out, as (role, receipt). A later generation carries the words of an earlier one with no export of its own beside them, and they are held to the same safeguards."""
    told = _ACCOUNT_OF_OBSERVATION.match(text)
    if told:
        return [(told.group('role'), dict(path=told.group('path'), expected_sha256=told.group('expected'), actual_sha256=told.group('actual'), retained_as=told.group('kept')))]
    told = _ACCOUNT_OF_EXPORT.match(text)
    if told:
        try:
            failed = ast.literal_eval(told.group('failed'))
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            return []
        return [(told.group('role'), item) for item in failed if isinstance(item, dict) and item.get('kind') == 'corrupt'] if isinstance(failed, list) else []
    return []


def _claim_problems(run_dir, claims, reasons, token, expected):
    """Whether every receipt a stop record presents, whichever kind of record it is, has what it would take to be a fact. ``claims`` are its receipts as (role, receipt), and ``reasons`` the words it gives, some of which spell out a receipt of their own.

    The same safeguards as an observation, and nothing recomputes an expected hash. Words that present no receipt have nothing here to be held to, and a reason that is no account of corrupt bytes is not touched and does not help one that is.
    """
    claims = list(claims)
    for text in reasons:
        if isinstance(text, str) and _tells_of_corrupt_bytes(text):
            claims += _receipts_told_in(text)
    problems = []
    for owner, item in claims:
        relative = item.get('path')
        found = _receipt_problems(run_dir, [item])
        if owner not in ('game', 'bot'):
            found.append('its receipt names role %r' % (owner,))
        if not _safe_inside(relative):
            found.append('its receipt names path %r' % (relative,))
        found += _fence_problems(token, expected)
        if not found:
            found = _corroboration_problems(run_dir, dict(role=owner, path=relative, expected_sha256=item['expected_sha256'], fencing_token=token), expected)
        problems += ['its receipt for %s of %s: %s' % (relative, owner, problem) for problem in found]
    return sorted(set(problems))


def _bound_to_dispatch(run_dir, expected):
    return dict(expected, dispatch_token=_dispatch_token(run_dir))


def corrupt_receipt_problems(run_dir, role, receipts, token, expected):
    """Before a controller calls bytes it just compared a demonstrated failure: whether what is on record supports the hash it compared them with. What does not stays unverified, and nothing irreversible follows from it."""
    run_dir = pathlib.Path(run_dir)
    return _claim_problems(run_dir, [(role, item) for item in receipts], [], token, _bound_to_dispatch(run_dir, expected))


def seal_reply_problems(run_dir, role, digest, seal, token, expected):
    """Whether a guest's reply can be what any byte of this role is judged against. What is already on record outranks it: a reply that names another seal is a stale or wrong reply and says nothing about the bytes, so nothing may be compared with it.

    With nothing on record, the reply is the first word and its receipt is retained before any byte. ``seal`` is the sealed document when the reply carried it.
    """
    run_dir = pathlib.Path(run_dir)
    expected = _bound_to_dispatch(run_dir, expected)
    if not is_digest(digest):
        return ['it names no seal digest']
    files = None
    if seal is not None:
        files = seal_inventory(seal, expected['run_id'], role)
        if files is None:
            return ['the seal it carries cannot be held to this run and role']
    receipts, problems = _seal_receipts(run_dir, role, token, expected)
    if problems:
        return problems
    others = sorted({item['seal_sha256'] for item in receipts} - {digest})
    if others:
        return ['it names seal %s, and the retained seal receipts say %s' % (digest, ', '.join(others))]
    if files is not None and any(item['files'] is not None and item['files'] != files for item in receipts):
        return ['the seal it carries does not list what the retained seal receipts list']
    problems = _execution_seal_problems(run_dir, role, digest, expected)[0]
    retained = file_sha256(run_dir / role / guest_runner.SEAL)
    if retained is not None and retained != digest:
        problems.append('it names seal %s, and the seal retained here is %s' % (digest, retained))
    return problems


def validation_guard_name(run_id, role, token, attempt):
    return '%s--%s-%04d-%d.json' % (run_id, role, token, attempt)


def validation_guard(session_id, manifest_sha256, run_id, role, token, opened_at):
    """What a controller puts on disk, acknowledged, before it compares any transferred byte of a role. See ``RunExecutor._begin_validation``."""
    return dict(schema=VALIDATION_GUARD_SCHEMA, session_id=session_id, manifest_sha256=manifest_sha256, run_id=run_id, role=role, fencing_token=token, opened_at=opened_at)


def validation_guards(run_dir):
    """Every guard of this run, by path. They sit beside ``runs/``: a guard inside the run directory would share the fate of the very writes it has to outlast."""
    run_dir = pathlib.Path(run_dir)
    directory = run_dir.parent.parent / VALIDATION_GUARD_DIR
    try:
        # glob suppresses directory read errors on supported Python versions.
        paths = list(directory.iterdir())
    except FileNotFoundError:
        # A legacy session may have no directory. A dangling link is an error.
        try:
            directory.lstat()
        except FileNotFoundError:
            return []
        raise
    return sorted(path for path in paths if path.name.startswith(run_dir.name + '--') and path.name.endswith('.json'))


def _unresolved_validations(run_dir, facts, expected):
    """Comparisons that began and that nothing says ended. The result could have been a failure whose record was lost, so this can never be read as a clean comparison, however good the bytes look now. A fact of the same role and no older is what such a comparison left, and has said all this could."""
    found = []
    for path in validation_guards(run_dir):
        record, problem = mw.load_json(path)
        problems = [problem] if problem else ['it is not a validation guard of schema %s' % VALIDATION_GUARD_SCHEMA] if not isinstance(record, dict) or record.get('schema') != VALIDATION_GUARD_SCHEMA else _identity_problems(record, expected)
        role, token = (record.get('role'), record.get('fencing_token')) if isinstance(record, dict) else (None, None)
        if not problems and any(fact.get('role') == role and isinstance(fact.get('fencing_token'), int) and isinstance(token, int) and fact['fencing_token'] >= token for fact in facts):
            continue
        name = '%s/%s' % (VALIDATION_GUARD_DIR, path.name)
        found.append(dict(record=name, sha256=file_sha256(path), problems=problems or ['a comparison of what %s sealed began under token %s and nothing says it ended, so its result may be a failure whose record was lost' % (role, token)]))
    return found


def is_validation_guard(item):
    """Whether an unverified record is an unresolved comparison, rather than a file that cannot be held to this run."""
    return item['record'] == VALIDATION_GUARD_DIR or item['record'].startswith(VALIDATION_GUARD_DIR + '/')


def _covered_by_a_fact(record, facts):
    """A fact that names these same bytes has already said all this observation can, so one failure stays one stop."""
    return any(fact.get('role') == record['role'] and any(item.get('path') == record['path'] and item.get('actual_sha256') == record['actual_sha256'] for item in fact.get('receipts') or ()) for fact in facts)


def _stop_list_problems(name, value):
    if value is None:
        return []
    if not isinstance(value, dict) or not all(isinstance(items, list) and all(isinstance(item, str) for item in items) for items in value.values()):
        return ['its %s are of no known shape' % name]
    return []


def execution_record_problems(record):
    """Whether an execution record has the shape its writer gives it, so that what it says of a stop can be read at all. Says nothing of whose it is."""
    if not isinstance(record, dict):
        return ['it is not a JSON object']
    if not isinstance(record.get('problems'), dict):
        return ['it holds no problems']
    problems = _stop_list_problems('problems', record['problems']) + _stop_list_problems('demonstrated problems', record.get('demonstrated_problems'))
    demonstrated = record.get('demonstrated_outcome')
    if demonstrated is not None:
        if not isinstance(demonstrated, dict) or not _stops(demonstrated.get('outcome')):     # its writer only ever demonstrates a stop, and a return would commit this as it stands
            problems.append('its demonstrated outcome is of no known shape')
        elif not (demonstrated.get('reasons') is None or (isinstance(demonstrated['reasons'], list) and all(isinstance(item, str) for item in demonstrated['reasons']))):
            problems.append('the reasons for its demonstrated outcome are of no known shape')
    if not isinstance(record.get('interrupted'), (str, type(None))):
        problems.append('what it says interrupted it is of no known shape')
    return problems


def _execution_claims(record):
    """Every account of corrupt bytes an execution record gives: (receipts as (role, receipt), reasons), from its own export and from the words it carries."""
    claims = []
    exported = record.get('exported')
    for role, view in exported.items() if isinstance(exported, dict) else ():
        failed = view.get('failed') if isinstance(view, dict) else None
        claims += [(role, item) for item in failed if isinstance(item, dict) and (item.get('kind') == 'corrupt' or 'expected_sha256' in item)] if isinstance(failed, list) else []
    reasons = [text for key in ('problems', 'demonstrated_problems') for items in (record.get(key) or {}).values() for text in items]
    demonstrated = record.get('demonstrated_outcome') or {}
    return claims, reasons + list(demonstrated.get('reasons') or ())


def supported_execution(run_dir, record, expected):
    """(what can be stood on, problems) for a well-shaped execution record of this run, of any generation. An account of corrupt bytes that what is on record does not support leaves the record, in every list that carries it, so it can neither be promoted here nor carried into the next generation and lose the distinction there.

    A reason of its own stays: that a record also tells an unsupported account says nothing of a host that rebooted, and that it tells of a host that rebooted says nothing for the account. A demonstrated outcome with nothing left to stand on goes with its account.
    """
    run_dir = pathlib.Path(run_dir)
    claims, reasons = _execution_claims(record)
    problems = _claim_problems(run_dir, claims, reasons, record.get('fencing_token'), _bound_to_dispatch(run_dir, expected))
    if not problems:
        return record, []

    def kept(items):
        return [text for text in items if not _tells_of_corrupt_bytes(text)]
    clean = dict(record, problems={kind: kept(items) for kind, items in record['problems'].items()}, demonstrated_problems={kind: kept(items) for kind, items in (record.get('demonstrated_problems') or {}).items()})
    demonstrated = record.get('demonstrated_outcome')
    if demonstrated is not None:
        own = kept(demonstrated.get('reasons') or ())
        clean['demonstrated_outcome'] = dict(demonstrated, reasons=own) if own else None
    return clean, problems


def _execution_stops(path, record):
    """What a well-shaped execution record says stopped."""
    found = []
    demonstrated = record.get('demonstrated_outcome') or {}
    if _stops(demonstrated.get('outcome')):
        found.append(dict(record=path.name, sha256=file_sha256(path), outcome=demonstrated['outcome'], details=list(demonstrated.get('reasons') or ())))
    details = (record.get('demonstrated_problems') or {}).get('infrastructure')
    if details:
        found.append(dict(record=path.name, sha256=file_sha256(path), outcome=search.INFRASTRUCTURE_FAILURE, details=list(details)))
    return found


def _execution_retained(record):
    """The corrupt bytes an execution record names, in its own export or in the words it carries."""
    claims, reasons = _execution_claims(record)
    claims += [told for text in reasons if _tells_of_corrupt_bytes(text) for told in _receipts_told_in(text)]
    for _, item in claims:
        if isinstance(item.get('retained_as'), str):
            yield item['retained_as'], item.get('actual_sha256')


def stop_records(run_dir, expected):
    """(facts, unverified) over this run's retained stop records, of every generation of controllers, whichever decision they sit beside. Pure over retained files, and total over whatever those files hold.

    ``facts`` are this run's own and can stop a session for good. ``unverified`` are files that say, or may be all that is left to say, that a run stopped, and that cannot be held to this session, manifest, run or shape: they prove nothing
    about this session, and neither does anything else in them, so nothing irreversible may be done on their word and no claim can stand beside them. What a host only failed to answer is kept under ``uncertain`` and is neither. An immutable
    decision stays what it was when it was made, so a fact found later is read from here and never from the decision.

    Corrupt bytes pass through a lifecycle (``RunExecutor._corrupt_receipt``), and a crash can leave any step of it. An observation with its bytes is a fact like a terminal fact. An observation short of its bytes, an interrupted write of any
    stop record, bytes nothing binds and a comparison that began and never said how it ended are unverified until someone looks at them. No later transfer that works can make any of them disappear.

    An account of corrupt bytes is held to the same older records in every form it takes, observation, terminal fact or execution record of any generation: what they contradict or do not support is unverified, and its record makes no fact of it. A stop reason that is no such account stands on its own.

    ``expected`` holds ``session_id``, ``manifest_sha256`` and ``run_id``, and may hold ``current_token``.
    """
    run_dir = pathlib.Path(run_dir)
    if not run_dir.is_dir():
        return [], [dict(record=run_dir.name, sha256=None, problems=['this run was dispatched and its directory is gone, with whatever it held: no crash takes a name that went durably onto disk before its dispatch'])]
    expected = dict(expected, dispatch_token=_dispatch_token(run_dir))
    facts, unverified, bound = [], [], {}

    def unread(path, error):
        unverified.append(dict(record=path.name, sha256=file_sha256(path), problems=['it could not be read: ' + type(error).__name__]))

    for path in sorted(run_dir.glob('execution*.json'), key=lambda item: (item.name != 'execution.json', item.name)):
        try:
            record, problem = mw.load_json(path)
            shape = [problem] if problem else execution_record_problems(record)
            if shape:
                unverified.append(dict(record=path.name, sha256=file_sha256(path), problems=shape))
                continue
            foreign = _identity_problems(record, expected)
            found = _execution_stops(path, record)
            if found and foreign:
                unverified.append(dict(record=path.name, sha256=file_sha256(path), problems=foreign))
            elif not foreign:
                supported, unsupported = supported_execution(run_dir, record, expected)
                facts += _execution_stops(path, supported)
                if unsupported:
                    unverified.append(dict(record=path.name, sha256=file_sha256(path), problems=unsupported))
                else:
                    bound.update(_execution_retained(record))
        except READ_FAILURES as error:
            unread(path, error)
    for path in sorted(run_dir.glob(TERMINAL_FACT_GLOB)):
        try:
            record, problem = mw.load_json(path)
            problems = [problem] if problem else _terminal_fact_problems(path, record, expected)
            if problems:
                unverified.append(dict(record=path.name, sha256=file_sha256(path), problems=problems))
            else:
                facts.append(dict(record=path.name, sha256=file_sha256(path), outcome=record['outcome'], details=list(record['details']), role=record['role'], fencing_token=record['fencing_token'], **({'receipts': record['receipts']} if record.get('receipts') else {})))
                bound.update((item['retained_as'], item['actual_sha256']) for item in record.get('receipts') or () if item.get('retained_as') is not None)
        except READ_FAILURES as error:
            unread(path, error)
    observed = []
    for path in sorted(run_dir.glob(CORRUPT_OBSERVATION_GLOB)):
        try:
            record, problem = mw.load_json(path)
            problems = [problem] if problem else _observation_problems(path, record, expected)
            if problems:
                unverified.append(dict(record=path.name, sha256=file_sha256(path), problems=problems))
            else:
                observed.append((path, record))
                bound[record['retained_as']] = record['actual_sha256']
        except READ_FAILURES as error:
            unread(path, error)
    known = list(facts)
    for path, record in observed:
        if _covered_by_a_fact(record, known):
            continue
        if file_sha256(run_dir / record['retained_as']) != record['actual_sha256']:
            unverified.append(dict(record=path.name, sha256=file_sha256(path), problems=['it says %s of %s failed its hash, and the bytes it names at %s are not here: a crash or a full disk may have left it so' % (record['role'], record['path'], record['retained_as'])]))
            continue
        receipt = {key: record[key] for key in ('path', 'reason', 'expected_sha256', 'actual_sha256', 'retained_as')}
        facts.append(dict(record=path.name, sha256=file_sha256(path), outcome=search.INFRASTRUCTURE_FAILURE, details=['%s %s failed its hash: expected %s, found %s, kept at %s' % (record['role'], record['path'], record['expected_sha256'], record['actual_sha256'], record['retained_as'])],
                          role=record['role'], fencing_token=record['fencing_token'], receipts=[receipt]))
    try:
        unverified += _unresolved_validations(run_dir, facts, expected)
    except READ_FAILURES as error:
        unverified.append(dict(record=VALIDATION_GUARD_DIR, sha256=None, problems=['whether a comparison of this run was left unfinished could not be read: ' + type(error).__name__]))
    try:
        unverified += _interrupted_stop_writes(run_dir) + _unbound_corrupt_bytes(run_dir, bound)
    except READ_FAILURES as error:
        unverified.append(dict(record=CORRUPT_EVIDENCE_DIR, sha256=None, problems=['what a crash may have left here could not be read: ' + type(error).__name__]))
    return facts, unverified


def _interrupted_stop_writes(run_dir):
    """A write of a stop record that never finished may be all that is left of what it was going to say. Beside a whole copy under its final name, it is only a temporary file a crash did not get to remove."""
    found = []
    for pattern in STOP_RECORD_WRITES:
        for path in sorted(run_dir.glob(pattern)):
            digest = file_sha256(path)
            if digest is None or digest != file_sha256(path.with_name(path.name.split(do_session.WRITING)[0])):
                found.append(dict(record=path.name, sha256=digest, problems=['it is an interrupted write of a stop record, and may be all that is left of what that record was going to say']))
    return found


def _unbound_corrupt_bytes(run_dir, bound):
    """Bytes kept apart as corrupt that no record of this run accounts for. Their name is not evidence of anything, so they make nobody's fact, and a claim still cannot stand beside them."""
    found = []
    root = run_dir / CORRUPT_EVIDENCE_DIR
    for path in sorted(root.rglob('*')):
        with contextlib.suppress(OSError):
            if path.is_dir():
                continue
        name = path.relative_to(run_dir).as_posix()
        digest = file_sha256(path)
        final = name.split(do_session.WRITING)[0]
        if digest is not None and final in bound and digest == bound[final]:
            continue
        found.append(dict(record=name, sha256=digest, problems=['it is kept as corrupt bytes, and no record of this run accounts for it: a crash or a full disk may have left it so']))
    return found


def _dispatch_token(run_dir):
    """The fencing token this run was dispatched under, when its grant is on record. No fact about a run can come from a controller older than that."""
    grant, problem = mw.load_json(pathlib.Path(run_dir) / 'grant.json')
    token = None if problem or not isinstance(grant, dict) else grant.get('fencing_token')
    return token if isinstance(token, int) and not isinstance(token, bool) else None


def load_retained(path):
    """The document, if the file is a whole score of this schema with its own content intact. Says nothing of whose it is."""
    with contextlib.suppress(OSError, ValueError, UnicodeDecodeError, RecursionError):
        text = pathlib.Path(path).read_text()
        document = json.loads(text)
        if isinstance(document, dict) and document.get('schema') == SCORE_SCHEMA and text == canonical(document) and seal(document) == document:
            return document
    return None


def bound_score(path, expected):
    """(document, problems) for a retained score. Empty problems is the only thing that lets anyone act on it, or on a claim resting on it. Total: whatever the file holds is an answer, and one this cannot finish reading is a refusal."""
    document = load_retained(path)
    if document is None:
        return None, ['it does not read as a whole score, or its content was changed after it was written']
    try:
        return document, _binding_problems(document, expected) + _result_problems(document)
    except READ_FAILURES as error:
        return document, ['it could not be read to the end: ' + type(error).__name__]


def classification_problems(document, expected, require_score=True):
    """Why a retained classification cannot stand for this run. A PASS or FAIL must rest on a bound score by the hash it recorded when it was written. ``require_score`` is False only for a fixture's scripted scorer. Total, like ``bound_score``."""
    try:
        return _classification_problems(document, expected, require_score)
    except READ_FAILURES as error:
        return ['it could not be read to the end: ' + type(error).__name__]


def _verdict_shape_problems(verdict):
    """What anyone reads back out of a verdict. A verdict of the wrong shape cannot be rendered, and it must not be committed on the way to finding that out."""
    reasons, supersedes = verdict.get('reasons'), verdict.get('supersedes')
    if not (reasons is None or (isinstance(reasons, list) and all(isinstance(item, str) for item in reasons))):
        return ['its verdict has reasons of no known shape']
    if not isinstance(supersedes, (list, type(None))) or not all(isinstance(item, dict) and isinstance(item.get('file'), str) and isinstance(item.get('sha256'), (str, type(None))) and isinstance(item.get('outcome'), (str, type(None))) for item in supersedes or ()):
        return ['its verdict supersedes files of no known shape']
    if not isinstance(verdict.get('evidence_ref'), (str, type(None))):
        return ['its verdict names evidence of no known shape']
    return []


def _classification_problems(document, expected, require_score):
    if not isinstance(document, dict) or document.get('schema') != CLASSIFICATION_SCHEMA:
        return ['it is not a classification of the expected schema']
    if document.get('run_id') != expected['run_id']:
        return ['it classifies run %r' % (document.get('run_id'),)]
    verdict = document.get('verdict')
    if not isinstance(verdict, dict) or verdict.get('outcome') not in search.OUTCOMES:
        return ['it holds no verdict with a known outcome']
    shape = _verdict_shape_problems(verdict)
    if shape:
        return shape
    if not require_score:
        return []
    reference = parse_reference(verdict.get('evidence_ref'))
    problems = []
    if verdict['outcome'] in search.ADVANCING and (verdict.get('scored') is not True or reference is None or reference[1] != SCORE_FILE):
        return ['it says %s and rests on no retained score' % verdict['outcome']]
    if reference is not None:
        run_id, name, digest = reference
        if run_id != expected['run_id']:
            problems.append('its evidence is of run %r' % run_id)
        elif file_sha256(expected['run_dir'] / name) != digest:
            problems.append('%s is no longer the file it recorded' % name)
        elif name == SCORE_FILE:
            score, more = bound_score(expected['run_dir'] / name, expected)
            problems += ['the score it rests on: ' + item for item in more]
            if score is not None and score.get('outcome') != verdict['outcome']:
                problems.append('it says %s and the score it rests on says %s' % (verdict['outcome'], score.get('outcome')))
    return problems
