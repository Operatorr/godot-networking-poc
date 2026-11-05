"""Whether a run's verified files prove one common scored interval. Pure over local files, with nothing live. It scores nothing.

The contract (issue #60 section 4, handoff slice 5) asks for four polling generator shards holding N authenticated bots through
one future interval, with the server's Ticks and transitions proving N throughout. This module answers only that question:

  complete      the whole interval is proven, on every recorder, and offered load was valid
  invalid       the evidence shows the interval or its offered load was broken, and says how
  inconclusive  the evidence cannot show it: missing, truncated, foreign or ambiguous

``PASS`` and capacity live in ``capacity_scorer`` (handoff slice 6, issue #69), which may only pass on ``complete``. The facts here carry no
gates: RTT, loss, Tick time and game-socket drops are kept for that scorer and judged by nothing in this file.

Time. Each process has its own monotonic domain with an arbitrary origin, and these are never compared directly. A boundary moves
between roles only through intervals: this process's monotonic reading to its host's wall clock (tight pairs, plus a drift
allowance), to the controller's clock and on to the other host (the before and after brackets, whichever is wider), then to that
process's monotonic reading. The result is an interval, and the server must prove N across all of it. A disconnect that
falls only in the uncertain part is ambiguous, which is inconclusive, and never a pass.

Missing is never zero: an absent counter, schedule, sample or row produces a reason. So does a document whose producer is not the one
this file understands. A hash proves the bytes arrived, not what they mean, so every versioned recorder is held to the frozen schema
before any of its fields are read.
"""
import csv
import hashlib
import json
import pathlib

SCHEMA_PATH = pathlib.Path(__file__).with_name('measurement_schema.json')
PROOF_SCHEMA = 'omega.do-session.window-proof/1'
COMPLETE, INVALID, INCONCLUSIVE = 'complete', 'invalid', 'inconclusive'
GENERATOR, SERVER, EVIDENCE, CLOCK = 'generator', 'server', 'evidence', 'clock'
NS = 1_000_000_000
ROLES = ('game', 'bot')


def schema():
    return json.loads(SCHEMA_PATH.read_text())


def schema_sha256():
    return hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest()


class Reasons:
    def __init__(self):
        self.items = []

    def add(self, code, category, detail=''):
        self.items.append(dict(code=code, category=category, detail=str(detail)[:600]))

    def status(self):
        categories = {item['category'] for item in self.items}
        if categories & {GENERATOR, SERVER}:
            return INVALID
        return INCONCLUSIVE if categories else COMPLETE


def load_ndjson(path):
    """(rows, problem). A line that does not parse is a truncation or a corruption, and which one is not this function's business."""
    try:
        data = pathlib.Path(path).read_bytes()
    except OSError:
        return [], 'missing'
    if data and not data.endswith(b'\n'):
        return [], 'truncated: the file does not end its last line'
    rows = []
    for number, line in enumerate(data.decode('utf-8', 'replace').splitlines()):
        try:
            rows.append(json.loads(line))
        except ValueError:
            return [], 'corrupt: line %d does not parse' % number
        if not isinstance(rows[-1], dict):
            return [], 'corrupt: line %d is not a row' % number
    return rows, None if rows else 'empty'


def load_json(path):
    try:
        document = json.loads(pathlib.Path(path).read_text())
    except OSError:
        return None, 'missing'
    except ValueError:
        return None, 'corrupt'
    return (document, None) if isinstance(document, dict) else (None, 'corrupt')


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_count(value):
    """A counter or a monotonic reading: a real non-negative integer, so that absent, null, text, a boolean or a negative are all no reading at all."""
    return is_int(value) and value >= 0


def check_producer(document, name, kind, reasons):
    """Whether this recorder's own schema and role are the frozen ones. Nothing else in it means anything until this is true."""
    frozen = schema()
    role = frozen['producers'][kind]
    found = (document.get('schema'), document.get('role')) if isinstance(document, dict) else (None, None)
    if found != (frozen['id'], role):
        reasons.add('schema_mismatch', EVIDENCE, '%s is schema %r role %r, this prover understands %s role %s' % (name, found[0], found[1], frozen['id'], role))
        return False
    return True


# ---- clocks ---------------------------------------------------------------------------------------

def valid_pair(pair):
    return isinstance(pair, dict) and all(is_int(pair.get(k)) for k in ('wall_before_ns', 'mono_ns', 'wall_after_ns')) and pair['wall_before_ns'] <= pair['wall_after_ns']


class Domain:
    """One process's monotonic clock against its own host's wall clock. Answers in intervals."""

    def __init__(self, name, pairs, limits):
        self.name = name
        self.pairs = sorted((pair for pair in pairs if valid_pair(pair)), key=lambda pair: pair['mono_ns'])
        self.drift = limits['clock_drift_ppm'] / 1e6
        self.max_age_ns = limits['pair_max_age_s'] * NS
        self.step_ns = limits['clock_step_ms'] * 1_000_000

    def steps(self):
        """Wall against monotonic should barely move. A jump between neighbouring pairs is a stepped wall clock, which breaks every mapping across it."""
        found = []
        for left, right in zip(self.pairs, self.pairs[1:]):
            before = (left['wall_before_ns'] + left['wall_after_ns']) // 2 - left['mono_ns']
            after = (right['wall_before_ns'] + right['wall_after_ns']) // 2 - right['mono_ns']
            allowance = self.step_ns + int(abs(right['mono_ns'] - left['mono_ns']) * self.drift)
            if abs(after - before) > allowance:
                found.append(dict(at_mono_ns=right['mono_ns'], jump_ns=after - before))
        return found

    def _nearest_mono(self, mono):
        return min(self.pairs, key=lambda pair: abs(pair['mono_ns'] - mono)) if self.pairs else None

    def to_wall(self, mono):
        pair = self._nearest_mono(mono)
        if pair is None or abs(pair['mono_ns'] - mono) > self.max_age_ns:
            return None
        distance = mono - pair['mono_ns']
        slack = int(abs(distance) * self.drift) + 1
        return pair['wall_before_ns'] + distance - slack, pair['wall_after_ns'] + distance + slack

    def to_mono(self, wall_low, wall_high):
        middle = (wall_low + wall_high) // 2
        pair = min(self.pairs, key=lambda item: abs((item['wall_before_ns'] + item['wall_after_ns']) // 2 - middle)) if self.pairs else None
        if pair is None or abs((pair['wall_before_ns'] + pair['wall_after_ns']) // 2 - middle) > self.max_age_ns:
            return None
        slack = int(max(abs(wall_low - pair['wall_after_ns']), abs(wall_high - pair['wall_before_ns'])) * self.drift) + 1
        return pair['mono_ns'] + wall_low - pair['wall_after_ns'] - slack, pair['mono_ns'] + wall_high - pair['wall_before_ns'] + slack


def bracket_offset(bracket, role):
    """(low, high, boot_id) of ``role wall minus controller wall``, from the bracket's raw attempts. The controller's own summary is not trusted."""
    if not isinstance(bracket, dict) or bracket.get('schema') != schema()['bracket_schema']:
        return None
    attempts = (bracket.get('roles') or {}).get(role) or []
    best = None
    for attempt in attempts if isinstance(attempts, list) else ():
        if not isinstance(attempt, dict) or not all(is_int(attempt.get(k)) for k in ('before_ns', 'guest_wall_ns', 'after_ns')) or attempt['after_ns'] < attempt['before_ns']:
            continue
        half = (attempt['after_ns'] - attempt['before_ns']) // 2 + 1
        middle = (attempt['after_ns'] + attempt['before_ns']) // 2
        offset = attempt['guest_wall_ns'] - middle
        if best is None or half < best[1]:
            best = (offset, half, attempt.get('boot_id'))
    return None if best is None else (best[0] - best[1], best[0] + best[1], best[2])


def host_offset(brackets, role, reasons):
    """Holds at any moment between the two brackets: linear change stays inside the hull of both."""
    readings = []
    for name in ('before', 'after'):
        reading = bracket_offset(brackets.get(name), role)
        if reading is None:
            reasons.add('clock_mapping_missing', CLOCK, 'no %s bracket for %s' % (name, role))
            return None
        readings.append(reading)
    if readings[0][2] and readings[1][2] and readings[0][2] != readings[1][2]:
        reasons.add('host_rebooted', CLOCK, '%s boot id changed between the brackets' % role)
    return min(readings[0][0], readings[1][0]), max(readings[0][1], readings[1][1]), readings[0][2]


# ---- the swarm's files ----------------------------------------------------------------------------

def check_stream(rows, nonce, name, reasons):
    """Numbered from zero, one nonce, header first, footer last. Anything else is not the whole of this recorder's output."""
    for index, row in enumerate(rows):
        if row.get('seq') != index:
            reasons.add('recorder_truncated', EVIDENCE, '%s: row %d carries sequence %s' % (name, index, row.get('seq')))
            return False
        if row.get('nonce') != nonce:
            reasons.add('recorder_overwritten', EVIDENCE, '%s: row %d belongs to another process' % (name, index))
            return False
    if not rows or rows[0].get('k') != 'header':
        reasons.add('recorder_truncated', EVIDENCE, '%s has no header' % name)
        return False
    if rows[-1].get('k') != 'footer':
        reasons.add('recorder_truncated', EVIDENCE, '%s has no footer' % name)
        return False
    failure = rows[-1].get('recorder_failure', 'its footer does not say')
    if failure is not None:
        reasons.add('recorder_failed', EVIDENCE, '%s: %s' % (name, failure))
        return False
    return True


def check_controls(controls, trial, workload, reasons):
    expected = dict(behavior=workload.get('behavior'), difficulty=workload.get('difficulty'), input_hz=workload.get('input_hz'), seed=workload.get('seed'),
                    threads=workload.get('generator_threads'), bot_id_assignment=workload.get('bot_id_assignment'), join_stagger_ms=workload.get('join_stagger_ms'),
                    bots=trial['target'], hold_s=trial['hold_s'])
    for key, value in expected.items():
        if controls.get(key) != value:
            reasons.add('workload_mismatch', EVIDENCE, '%s is %r, the trial says %r' % (key, controls.get(key), value))
    timing = schema()['swarm_timing_ns']
    for key, value in (('warmup_ns', timing['warmup']), ('publish_lead_ns', timing['publish_lead']), ('end_guard_ns', timing['end_guard']), ('drain_ns', timing['drain'])):
        if controls.get(key) != value:
            reasons.add('workload_mismatch', EVIDENCE, '%s is %r, the schema says %r' % (key, controls.get(key), value))
    faults = controls.get('faults')
    if not isinstance(faults, list):
        reasons.add('workload_mismatch', EVIDENCE, 'the swarm does not state its faults: %r' % (faults,))
    elif faults:
        reasons.add('fault_injection_build', EVIDENCE, 'this run was deliberately broken: %s' % faults)


def check_build(swarm, reasons):
    """A fault build can never prove a window, even with nothing injected: its binary is not the frozen one. Only the build itself can say, so an unstated build is no build."""
    stated = (swarm.get('build') or {}).get('fault_injection') if isinstance(swarm.get('build'), dict) else None
    if stated is True:
        reasons.add('fault_injection_build', EVIDENCE, 'this binary was built with fault injection')
    elif stated is not False:
        reasons.add('build_unstated', EVIDENCE, 'swarm.json does not state its build: %r' % (stated,))


def check_boundaries(rows, name, start, end, footer, reasons):
    """The boundary rows of one shard, in the only order a real shard can write them, each with a real time. Returns freeze, or None when there is none.

    A counter snapshot proves only what came before it. One taken before the end, or one that carries the right boundary labels but no time of its own, cannot prove the rest of the hold.
    """
    found = {}
    for kind in ('window_observed', 'ack_start', 'ack_end', 'freeze', 'drain_start'):
        matching = [row for row in rows if row.get('k') == kind]
        if len(matching) > 1:
            reasons.add('boundary_contradiction', EVIDENCE, '%s has %d %s rows' % (name, len(matching), kind))
        if matching:
            found[kind] = matching[0]
    freeze, drain, ack_end = found.get('freeze'), found.get('drain_start'), found.get('ack_end')
    if freeze is None:
        reasons.add('counters_not_frozen', GENERATOR, name)
        return None
    if freeze.get('start_ns') != start or freeze.get('end_ns') != end:
        reasons.add('freeze_mismatch', EVIDENCE, '%s froze another window' % name)
    frozen_at = freeze.get('mono_ns')
    if not is_count(frozen_at):
        reasons.add('freeze_time_missing', EVIDENCE, '%s froze at %r' % (name, frozen_at))
    elif frozen_at < end:
        reasons.add('frozen_before_end', EVIDENCE, '%s froze %.3f s before the end' % (name, (end - frozen_at) / NS))
    if ack_end is not None and is_count(ack_end.get('mono_ns')) and (ack_end['seq'] > freeze['seq'] or (is_count(frozen_at) and frozen_at < ack_end['mono_ns'])):
        reasons.add('frozen_before_end_acknowledgment', EVIDENCE, '%s froze at %r before acknowledging the end at %r' % (name, frozen_at, ack_end['mono_ns']))
    if drain is None:
        if footer.get('left_early') is False:
            reasons.add('drain_missing', EVIDENCE, '%s finished with no drain record' % name)
    else:
        if drain['seq'] < freeze['seq'] or (is_count(frozen_at) and is_count(drain.get('mono_ns')) and drain['mono_ns'] < frozen_at):
            reasons.add('drained_before_freeze', GENERATOR, name)
        if not is_count(drain.get('mono_ns')):
            reasons.add('drain_time_missing', EVIDENCE, '%s drained at %r' % (name, drain.get('mono_ns')))
        elif drain['mono_ns'] < end:
            reasons.add('drained_before_end', GENERATOR, name)
    ordered = [found[kind] for kind in ('window_observed', 'ack_start', 'ack_end', 'freeze', 'drain_start') if kind in found] + [footer]
    for left, right in zip(ordered, ordered[1:]):
        out_of_order = left['seq'] > right['seq'] or (is_count(left.get('mono_ns')) and is_count(right.get('mono_ns')) and left['mono_ns'] > right['mono_ns'])
        if out_of_order and {left['k'], right['k']} not in ({'ack_end', 'freeze'}, {'freeze', 'drain_start'}):
            reasons.add('boundary_contradiction', EVIDENCE, '%s: %s comes before %s' % (name, right['k'], left['k']))
    return freeze


def check_shard(shard, shards, nonce, rows, bots, start, end, limits, reasons):
    """One shard's file. Returns its per-bot facts, or None if the file cannot be trusted."""
    name = 'shard-%d' % shard
    if not check_stream(rows, nonce, name, reasons):
        return None
    header = rows[0]
    if not check_producer(header, name, 'shard-<k>.ndjson', reasons):
        return None
    if header.get('shard') != shard or header.get('shards') != shards:
        reasons.add('ownership_mismatch', EVIDENCE, '%s says it is shard %r of %r' % (name, header.get('shard'), header.get('shards')))
    owned = header.get('bots') or []
    expected = [bot for bot in range(1, bots + 1) if (bot - 1) % shards == shard]
    if owned != expected:
        reasons.add('ownership_mismatch', EVIDENCE, '%s owns %s, round-robin says %s' % (name, owned, expected))
    if ((header.get('geometry') or {}).get('initialized_on_thread')) is not True:
        reasons.add('geometry_not_initialized', GENERATOR, name)
    joins = {row.get('bot'): row for row in rows if row.get('k') == 'join'}
    auths = {row.get('bot'): row for row in rows if row.get('k') == 'auth'}
    stagger_ns = limits['stagger_tolerance_ms'] * 1_000_000
    for bot in expected:
        join = joins.get(bot)
        if join is None or join.get('error'):
            reasons.add('join_missing', GENERATOR, 'bot %d: %s' % (bot, (join or {}).get('error')))
            continue
        scheduled, actual = join.get('scheduled_ns'), join.get('actual_ns')
        if not is_int(scheduled) or not is_int(actual):
            reasons.add('join_missing', EVIDENCE, 'bot %d has no join times' % bot)
        elif actual - scheduled > stagger_ns:
            reasons.add('global_stagger_violated', GENERATOR, 'bot %d joined %.1f ms after its slot' % (bot, (actual - scheduled) / 1e6))
        if bot not in auths:
            reasons.add('bot_never_authenticated', GENERATOR, 'bot %d' % bot)
    starvation_ns = limits['poll_starvation_ms'] * 1_000_000
    footer = rows[-1]
    gaps = [row.get('max_poll_gap_ns') for row in rows if row.get('k') == 'sample']
    if not is_count(footer.get('max_poll_gap_ns')) or not gaps or not all(is_count(gap) for gap in gaps):
        reasons.add('poll_liveness_missing', EVIDENCE, name)
    elif footer['max_poll_gap_ns'] > starvation_ns:
        reasons.add('poll_starvation', GENERATOR, '%s did not poll for %.0f ms' % (name, footer['max_poll_gap_ns'] / 1e6))
    if footer.get('left_early') is not False:
        if footer.get('left_early') is True:
            reasons.add('early_shard_exit', GENERATOR, name)
        else:
            reasons.add('poll_liveness_missing', EVIDENCE, '%s does not say whether it left early: %r' % (name, footer.get('left_early')))
    observed = next((row for row in rows if row.get('k') == 'window_observed'), None)
    if observed is None:
        reasons.add('window_not_observed', GENERATOR, name)
    elif not is_int(observed.get('mono_ns')) or observed['mono_ns'] >= start:
        reasons.add('window_observed_late', GENERATOR, '%s saw the published window at %s, the start was %s' % (name, observed.get('mono_ns'), start))
    late = limits['ack_lateness_ms'] * 1_000_000
    for kind, boundary in (('ack_start', start), ('ack_end', end)):
        ack = next((row for row in rows if row.get('k') == kind), None)
        if ack is None or not is_int(ack.get('mono_ns')):
            reasons.add('missing_acknowledgment', GENERATOR, '%s has no %s' % (name, kind))
        elif ack['mono_ns'] < boundary:
            reasons.add('acknowledged_early', EVIDENCE, '%s %s precedes its boundary' % (name, kind))
        elif ack['mono_ns'] - boundary > late:
            reasons.add('poll_starvation', GENERATOR, '%s %s was %.0f ms late' % (name, kind, (ack['mono_ns'] - boundary) / 1e6))
    freeze = check_boundaries(rows, name, start, end, footer, reasons)
    if freeze is None:
        return None
    frozen = {row.get('id'): row for row in freeze.get('bots') or [] if isinstance(row, dict)}
    samples = peer_coverage(rows, start, end)
    return dict(frozen=frozen, auths=auths, joins=joins, samples=samples, max_poll_gap_ns=footer.get('max_poll_gap_ns'), observer_ns=footer.get('observer_ns'), polls=footer.get('polls'), expected=expected)


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def peer_coverage(rows, start, end):
    """Timestamped ENet samples per bot, in the window only. Counted and returned as data: judging RTT or loss is the scorer's."""
    fields = next((row.get('bot_fields') for row in rows if row.get('k') == 'header'), None) or []
    try:
        index_id, index_peer = fields.index('id'), fields.index('peer')
    except ValueError:
        return {}
    found = {}
    for row in rows:
        if row.get('k') in ('sample', 'drain_end'):
            for item in row.get('bots') or []:
                if isinstance(item, list) and len(item) > max(index_id, index_peer):
                    for sample in item[index_peer] or []:
                        # A sample with no RTT or loss in it is no sample, however well timed.
                        if isinstance(sample, list) and len(sample) == 3 and is_count(sample[0]) and start <= sample[0] < end and is_number(sample[1]) and sample[1] >= 0 and is_count(sample[2]):
                            found.setdefault(item[index_id], []).append(sample)
    return found


# Every one of these must be a real count on every frozen row. Any other value is no observation.
FROZEN_COUNTS = ('scheduled', 'sent', 'send_errors', 'dead_frames', 'gap_max_ns', 'decode_failures', 'errors', 'panics', 'socket_send_errors', 'socket_zero_sends', 'socket_receive_errors')
GAP_BUCKETS = 8


def frozen_problems(row, start, end):
    """What makes this frozen row unusable as evidence, before any value on it is judged. Empty when every required field is an honest observation."""
    problems = ['%s is %r' % (field, row.get(field)) for field in FROZEN_COUNTS if not is_count(row.get(field))]
    if row.get('scheduled') == 0:
        problems.append('scheduled is 0')
    if not isinstance(row.get('phase'), str) or not row['phase']:
        problems.append('phase is %r' % (row.get('phase'),))
    if not isinstance(row.get('alive'), bool):
        problems.append('alive is %r' % (row.get('alive'),))
    buckets = row.get('gap_buckets')
    if not isinstance(buckets, list) or len(buckets) != GAP_BUCKETS or not all(is_count(value) for value in buckets):
        problems.append('gap_buckets is %r' % (buckets,))
    last = row.get('last_input_ns')
    if last is not None and not is_count(last):
        problems.append('last_input_ns is %r' % (last,))
    if 'disconnected' not in row:
        problems.append('disconnected is absent')
    disconnected = row.get('disconnected')
    if disconnected is not None:
        if not isinstance(disconnected, dict) or not is_count(disconnected.get('at_ns')) or not is_count(disconnected.get('reason')) or not isinstance(disconnected.get('expected'), bool):
            problems.append('disconnected is %r' % (disconnected,))
        elif not is_count(row.get('scheduled_before_disconnect')) or (is_count(row.get('scheduled')) and row['scheduled_before_disconnect'] > row['scheduled']):
            problems.append('scheduled_before_disconnect is %r' % (row.get('scheduled_before_disconnect'),))
    if not problems:
        if row['dead_frames'] > row['sent']:
            problems.append('%d dead frames of %d sent' % (row['dead_frames'], row['sent']))
        if row['sent'] and last is None:
            problems.append('sent %d with no last input' % row['sent'])
        if last is not None and not start <= last < end:
            problems.append('its last scored input at %d is outside the window' % last)
    return problems


def check_offered_load(shard_facts, start, end, hold_s, input_hz, limits, reasons):
    """Per bot, exact and in integers: at least 99% of its own scheduled frames. Exactly 99% is valid. Missing is not zero.

    A disconnected bot is held to the same floor over the part of the window it was connected for, less the one slot the disconnect can interrupt. Its frames after the
    disconnect are not owed, and this says nothing of who caused it: raw counters stay in the facts for the scorer to attribute.
    """
    facts = []
    percent = limits['input_min_percent']

    def coverage_floor(seconds):    # samples are about 1 Hz and drift later with each poll, and one can fall just outside either edge
        return int(limits['rtt_min_coverage'] * seconds) - 1

    for shard in shard_facts:
        for bot in shard['expected']:
            row = shard['frozen'].get(bot)
            if row is None:
                reasons.add('input_record_missing', EVIDENCE, 'bot %d has no frozen row' % bot)
                continue
            problems = frozen_problems(row, start, end)
            if problems:
                reasons.add('input_record_missing', EVIDENCE, 'bot %d: %s' % (bot, '; '.join(problems)))
                continue
            scheduled, sent, errors = row['scheduled'], row['sent'], row['send_errors']
            disconnected = row['disconnected']
            samples = shard['samples'].get(bot) or []
            facts.append(dict(bot=bot, scheduled=scheduled, sent=sent, send_errors=errors, gap_max_ns=row['gap_max_ns'], dead_frames=row['dead_frames'], peer_samples=len(samples),
                              ratio=sent / scheduled, disconnected=disconnected, scheduled_before_disconnect=row.get('scheduled_before_disconnect')))
            if abs(scheduled - hold_s * input_hz) > 1:
                reasons.add('schedule_mismatch', EVIDENCE, 'bot %d was owed %d frames in %d s at %s Hz' % (bot, scheduled, hold_s, input_hz))
            if sent > scheduled:
                reasons.add('schedule_mismatch', EVIDENCE, 'bot %d sent %d of %d' % (bot, sent, scheduled))
            if errors or row['errors'] or row['panics'] or row['decode_failures']:
                reasons.add('bot_errors', GENERATOR, 'bot %d: send %s errors %s panics %s decode %s' % (bot, errors, row['errors'], row['panics'], row['decode_failures']))
            sockets = [row[field] for field in ('socket_send_errors', 'socket_zero_sends', 'socket_receive_errors')]
            if any(sockets):
                # Counted from the socket's creation, so a failure in the ramp stops the claim too: conservative, and it can only refuse.
                reasons.add('generator_socket_errors', GENERATOR, 'bot %d: send errors %d, unsent datagrams %d, receive errors %d' % (bot, sockets[0], sockets[1], sockets[2]))
            if disconnected is not None:
                owed = row['scheduled_before_disconnect']
                connected_s = (min(max(disconnected['at_ns'], start), end) - start) // NS
                if (sent + 1) * 100 < owed * percent:
                    reasons.add('offered_input_below_minimum', GENERATOR, 'bot %d sent %d of the %d frames scheduled before it disconnected' % (bot, sent, owed))
                if len(samples) < coverage_floor(connected_s):
                    reasons.add('peer_sample_coverage', GENERATOR, 'bot %d has %d ENet samples in the %d s before it disconnected' % (bot, len(samples), connected_s))
                continue
            if sent * 100 < scheduled * percent:
                reasons.add('offered_input_below_minimum', GENERATOR, 'bot %d sent %d of %d scheduled frames while connected' % (bot, sent, scheduled))
            if len(samples) < max(1, coverage_floor(hold_s)):
                reasons.add('peer_sample_coverage', GENERATOR, 'bot %d has %d ENet samples in a %d s window' % (bot, len(samples), hold_s))
    return facts


def load_swarm(root, trial, workload, limits, reasons):
    """Everything that does not need the other host. Returns the bot-domain view, or None when no interval exists to talk about."""
    swarm_dir = root / 'bot' / 'swarm'
    swarm, problem = load_json(swarm_dir / 'swarm.json')
    window, window_problem = load_json(swarm_dir / 'window.json')
    if problem or window_problem:
        reasons.add('swarm_evidence_missing', EVIDENCE, 'swarm.json %s, window.json %s' % (problem, window_problem))
        return None
    if not check_producer(swarm, 'swarm.json', 'swarm.json', reasons) or not check_producer(window, 'window.json', 'window.json', reasons):
        return None
    nonce = swarm.get('nonce')
    if window.get('nonce') != nonce:
        reasons.add('recorder_overwritten', EVIDENCE, 'window.json belongs to another process')
    check_build(swarm, reasons)
    controls = swarm.get('controls') or {}
    check_controls(controls, trial, workload, reasons)
    if window.get('status') == 'not_established':
        reasons.add('window_not_established', GENERATOR, window.get('reason'))
        return None
    start, end = window.get('start_ns'), window.get('end_ns')
    if not is_int(start) or not is_int(end):
        reasons.add('window_boundaries_missing', EVIDENCE, 'status %s' % window.get('status'))
        return None
    hold_ns = trial['hold_s'] * NS
    if end - start != hold_ns:
        reasons.add('window_length_mismatch', EVIDENCE, 'end minus start is %d ns, the trial holds %d ns' % (end - start, hold_ns))
    if window.get('status') != 'window_recorded':
        reasons.add('window_incomplete', GENERATOR, window.get('reason') or window.get('status'))
    final_auth = window.get('final_auth_ns')
    warmup, lead = controls.get('warmup_ns'), controls.get('publish_lead_ns')
    if not is_int(final_auth) or not is_int(warmup) or not is_int(lead):
        reasons.add('window_boundaries_missing', EVIDENCE, 'final authentication or warmup')
    elif start < final_auth + warmup:
        reasons.add('warmup_violated', GENERATOR, 'the window starts %.3f s after the final authentication' % ((start - final_auth) / NS))
    bound_s = controls.get('readiness_timeout_s')
    if not is_number(bound_s):
        reasons.add('window_boundaries_missing', EVIDENCE, 'no readiness bound')
    elif is_int(final_auth) and final_auth > bound_s * NS:
        reasons.add('readiness_bound_exceeded', GENERATOR, 'the final authentication came %.3f s after the start, the bound is %s s' % (final_auth / NS, bound_s))
    coordinator, problem = load_ndjson(swarm_dir / 'coordinator.ndjson')
    pairs = []
    published = None
    if problem:
        reasons.add('recorder_truncated', EVIDENCE, 'coordinator.ndjson %s' % problem)
    elif check_stream(coordinator, nonce, 'coordinator', reasons) and check_producer(coordinator[0], 'coordinator.ndjson', 'coordinator.ndjson', reasons):
        published = next((row for row in coordinator if row.get('k') == 'window_published'), None)
        for row in coordinator:
            if valid_pair(row.get('clock')):
                pairs.append(row['clock'])
    if published is None:
        reasons.add('window_publish_missing', EVIDENCE, 'no publication record')
    elif published.get('start_ns') != start or published.get('end_ns') != end:
        reasons.add('window_publish_mismatch', EVIDENCE, 'window.json disagrees with what was published')
    elif not is_int(published.get('mono_ns')) or published['mono_ns'] >= start:
        reasons.add('window_not_future', GENERATOR, 'published at %s for a start at %s' % (published.get('mono_ns'), start))
    shards = controls.get('threads')
    if not is_int(shards) or shards <= 0:
        reasons.add('swarm_evidence_missing', EVIDENCE, 'no shard count')
        return None
    panicked, unjoined = window.get('panicked_shards'), window.get('unjoined_shards')
    if not isinstance(panicked, list) or not isinstance(unjoined, list):
        reasons.add('swarm_evidence_missing', EVIDENCE, 'window.json does not say which shards ended: panicked %r, unjoined %r' % (panicked, unjoined))
    elif panicked or unjoined:
        reasons.add('early_shard_exit', GENERATOR, 'panicked %s, unjoined %s' % (panicked, unjoined))
    facts = []
    for shard in range(shards):
        rows, problem = load_ndjson(swarm_dir / ('shard-%d.ndjson' % shard))
        if problem:
            reasons.add('recorder_truncated' if problem != 'missing' else 'shard_evidence_missing', EVIDENCE, 'shard-%d.ndjson %s' % (shard, problem))
            continue
        fact = check_shard(shard, shards, nonce, rows, trial['target'], start, end, limits, reasons)
        if fact is not None:
            facts.append(fact)
    offered = check_offered_load(facts, start, end, trial['hold_s'], controls.get('input_hz') or 0, limits, reasons) if facts else []
    domain = Domain('swarm', pairs, limits)
    entity_by_bot = {}
    ports = {}
    for shard in facts:
        for bot, row in shard['auths'].items():
            entity_by_bot[bot] = row.get('entity_id')
        for bot, row in shard['joins'].items():
            ports[bot] = row.get('local_port')
    return dict(swarm=swarm, window=window, start=start, end=end, final_auth=final_auth, domain=domain, shard_facts=facts, offered=offered, entity_by_bot=entity_by_bot, ports=ports, controls=controls)


# ---- the game's files -----------------------------------------------------------------------------

def load_game(root, reasons, limits):
    directory = root / 'game' / 'telemetry'
    process, problem = load_json(directory / 'process.json')
    final, final_problem = load_json(directory / 'final.json')
    population, population_problem = load_ndjson(directory / 'population.ndjson')
    if problem or population_problem:
        cut = population_problem not in (None, 'missing', 'empty')
        reasons.add('recorder_truncated' if cut else 'server_evidence_missing', EVIDENCE, 'process.json %s, population.ndjson %s' % (problem, population_problem))
        return None
    if final_problem:
        reasons.add('recorder_truncated', EVIDENCE, 'telemetry/final.json %s: the server never finished its recorders' % final_problem)
        return None
    if not check_producer(process, 'process.json', 'process.json', reasons) or not check_producer(final, 'final.json', 'final.json', reasons):
        return None
    for index, row in enumerate(population):
        if row.get('seq') != index:
            reasons.add('recorder_truncated', EVIDENCE, 'population.ndjson row %d carries sequence %s' % (index, row.get('seq')))
            return None
    if final.get('population_rows') != len(population) or population[-1].get('k') != 'footer':
        reasons.add('recorder_truncated', EVIDENCE, 'population.ndjson has %d rows, final.json says %s' % (len(population), final.get('population_rows')))
        return None
    ticks = []
    try:
        with (directory / 'ticks.csv').open(newline='') as handle:
            for row in csv.DictReader(handle):
                ticks.append((int(row['mono_ns']), int(row['tick']), int(row['authenticated']), int(row['work_ns'])))
    except (OSError, ValueError, TypeError, KeyError) as error:
        reasons.add('recorder_truncated', EVIDENCE, 'ticks.csv: %s' % type(error).__name__)
        return None
    if final.get('tick_rows') != len(ticks):
        reasons.add('recorder_truncated', EVIDENCE, 'ticks.csv has %d rows, final.json says %s' % (len(ticks), final.get('tick_rows')))
        return None
    if not ticks:
        reasons.add('server_evidence_missing', EVIDENCE, 'no Tick rows')
        return None
    pairs = [row['clock'] for row in population if valid_pair(row.get('clock'))]
    if valid_pair(process.get('clock')):
        pairs.insert(0, process['clock'])
    return dict(process=process, final=final, population=population, ticks=ticks, domain=Domain('server', pairs, limits))


def check_population(game, swarm, interval, core, trial, reasons):
    """N in every Tick across the whole uncertain interval, and transitions that agree. A loss only in the uncertain fringe is ambiguous, never a pass."""
    low, high = interval
    core_low, core_high = core
    expected = trial['target']
    ticks = game['ticks']
    first_mono, last_mono = ticks[0][0], ticks[-1][0]
    if first_mono > low or last_mono < high:
        reasons.add('server_tick_coverage', EVIDENCE, 'Ticks cover %d..%d, the interval needs %d..%d' % (first_mono, last_mono, low, high))
    inside = [tick for tick in ticks if low <= tick[0] <= high]
    facts = dict(ticks_in_interval=len(inside), interval_game_mono_ns=[low, high], core_game_mono_ns=[core_low, core_high], max_tick_gap_ns=None, tick_numbers_contiguous=None)
    if not inside:
        reasons.add('server_tick_coverage', EVIDENCE, 'no Tick inside the interval')
        return facts
    wrong_core = [tick for tick in inside if tick[2] != expected and core_low <= tick[0] <= core_high]
    wrong_fringe = [tick for tick in inside if tick[2] != expected and not core_low <= tick[0] <= core_high]
    if wrong_core:
        reasons.add('population_lost_in_window', SERVER, '%d Ticks held other than %d, first tick %d held %d' % (len(wrong_core), expected, wrong_core[0][1], wrong_core[0][2]))
    elif wrong_fringe:
        reasons.add('population_boundary_ambiguous', CLOCK, '%d Ticks at the uncertain edge held other than %d' % (len(wrong_fringe), expected))
    numbers = [tick[1] for tick in inside]
    facts['tick_numbers_contiguous'] = all(right - left == 1 for left, right in zip(numbers, numbers[1:]))
    if not facts['tick_numbers_contiguous']:
        reasons.add('server_tick_gap', EVIDENCE, 'Tick numbers skip inside the interval')
    facts['max_tick_gap_ns'] = max((right[0] - left[0] for left, right in zip(inside, inside[1:])), default=None)
    authenticated = {}
    disconnects = []
    for row in game['population']:
        if row.get('k') == 'auth':
            authenticated.setdefault(row.get('name'), row)
        elif row.get('k') == 'disconnect':
            disconnects.append(row)
        elif row.get('k') in ('connect_rejected', 'auth_rejected'):
            reasons.add('server_refused_a_join', SERVER, '%s reason %s' % (row.get('k'), row.get('reason')))
    for bot in range(1, expected + 1):
        name = 'LoadBot%03d' % bot
        row = authenticated.get(name)
        if row is None:
            reasons.add('server_auth_evidence_missing', EVIDENCE, 'no server auth row for %s' % name)
            continue
        if bot in swarm['entity_by_bot'] and swarm['entity_by_bot'][bot] != row.get('entity_id'):
            reasons.add('entity_identity_mismatch', EVIDENCE, '%s is entity %s to the server and %s to the swarm' % (name, row.get('entity_id'), swarm['entity_by_bot'].get(bot)))
        if not is_int(row.get('mono_ns')):
            reasons.add('server_auth_evidence_missing', EVIDENCE, '%s has no time' % name)
        elif row['mono_ns'] > core_low:
            reasons.add('population_lost_in_window', SERVER, '%s authenticated inside the window' % name)
        elif row['mono_ns'] > low:
            reasons.add('population_boundary_ambiguous', CLOCK, '%s authenticated inside the clock uncertainty' % name)
    for row in disconnects:
        at = row.get('mono_ns')
        if not is_int(at):
            reasons.add('server_auth_evidence_missing', EVIDENCE, 'a disconnect has no time')
        elif core_low <= at <= core_high:
            reasons.add('population_lost_in_window', SERVER, '%s disconnected in the window, reason %s' % (row.get('name'), row.get('reason')))
        elif low <= at <= high:
            reasons.add('population_boundary_ambiguous', CLOCK, '%s disconnected at the uncertain edge, reason %s' % (row.get('name'), row.get('reason')))
    facts['authenticated_transitions'] = len(authenticated)
    facts['disconnect_transitions'] = len(disconnects)
    return facts


# ---- role collectors and sockets ------------------------------------------------------------------

def load_sampler(root, role, reasons):
    """The collector's rows, once its own header says it is the frozen collector."""
    path = root / role / 'sampler.ndjson'
    try:
        data = path.read_bytes()
    except OSError:
        reasons.add('collector_evidence_missing', EVIDENCE, '%s sampler.ndjson' % role)
        return []
    if data and not data.endswith(b'\n'):
        data = data[:data.rfind(b'\n') + 1]     # the collector dies by signal, so a cut last row is expected, and bracketing below decides whether it mattered
    rows, metas = [], []
    for line in data.decode('utf-8', 'replace').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            reasons.add('recorder_truncated', EVIDENCE, '%s sampler.ndjson has a corrupt row' % role)
            return []
        if isinstance(row, dict) and row.get('kind') == 'meta':
            metas.append(row)
        elif isinstance(row, dict) and valid_pair(row.get('clock')):
            rows.append(row)
    versions = {row.get('schema') for row in metas}
    if versions != {schema()['id']}:
        reasons.add('schema_mismatch', EVIDENCE, '%s sampler.ndjson is schema %s, this prover understands %s' % (role, sorted(str(version) for version in versions), schema()['id']))
        return []
    return rows


def counter_read_bounds(row, limits):
    """(earliest, latest) host wall time at which this row's counters can have been read, or None when the row cannot say.

    The read happened somewhere between ``clock`` and ``clock_after``. ``collector_ns`` is the row's whole cost, so it must contain that span, and it widens both ends: a collector
    descheduled around either reading could have read that much further out. A wall clock that moved differently from the monotonic one inside the read leaves no bound at all.
    """
    before, after, cost = row.get('clock'), row.get('clock_after'), row.get('collector_ns')
    if not valid_pair(before) or not valid_pair(after) or not is_count(cost):
        return None
    span = after['mono_ns'] - before['mono_ns']
    if span < 0 or span > cost or after['wall_after_ns'] < before['wall_before_ns']:
        return None
    wall_span = (after['wall_before_ns'] + after['wall_after_ns']) // 2 - (before['wall_before_ns'] + before['wall_after_ns']) // 2
    if abs(wall_span - span) > limits['clock_step_ms'] * 1_000_000:
        return None
    slack = int(cost * limits['clock_drift_ppm'] / 1e6) + 1
    return min(before['wall_before_ns'], after['wall_after_ns'] - cost) - slack, max(after['wall_after_ns'], before['wall_before_ns'] + cost) + slack


def role_window(rows, wall_low, wall_high, role, limits, reasons):
    """The rows whose counters bracket the interval, baseline and final included.

    The baseline's read must have finished before the earliest possible start, and the final read must have begun after the latest possible end. A read that straddles a boundary may or
    may not hold what happened during it, so it is neither. Whatever these rows then count can only be a wider interval than the real one, so a drop is counted and never hidden.
    """
    monos = [row['clock']['mono_ns'] for row in rows]
    if any(right <= left for left, right in zip(monos, monos[1:])):
        reasons.add('collector_boundary_missing', EVIDENCE, '%s collector rows are out of order' % role)
        return None
    bounds = [counter_read_bounds(row, limits) for row in rows]
    before = [index for index, bound in enumerate(bounds) if bound is not None and bound[1] <= wall_low]
    after = [index for index, bound in enumerate(bounds) if bound is not None and bound[0] >= wall_high]
    if not before or not after:
        reasons.add('collector_boundary_missing', EVIDENCE, '%s collector has no counter read wholly %s the interval' % (role, 'before' if not before else 'after'))
        return None
    chosen = rows[before[-1]:after[0] + 1]
    gap = max((right['clock']['mono_ns'] - left['clock']['mono_ns'] for left, right in zip(chosen, chosen[1:])), default=0)
    if gap > limits['collector_max_gap_s'] * NS:
        reasons.add('collector_gap', EVIDENCE, '%s collector was silent for %.1f s' % (role, gap / NS))
    return chosen


def check_process_identity(rows, role, name, expected, prior, reasons):
    """Same pid, same kernel start, same boot, in every row. A pid that comes back with another start time is another process."""
    pid, start_id, boot = (expected or {}).get('pid'), (expected or {}).get('start_id'), (expected or {}).get('boot_id')
    if not is_int(pid) or not start_id:
        reasons.add('identity_missing', EVIDENCE, '%s has no recorded process identity' % role)
        return
    if (pid, start_id, boot) in prior:
        reasons.add('process_identity_reused', EVIDENCE, '%s %s was used by an earlier run' % (role, pid))
    for row in rows:
        facts = (row.get('procs') or {}).get(name)
        if not isinstance(facts, dict) or facts.get('alive') is not True:
            reasons.add('process_lost_in_window', EVIDENCE, '%s %s absent from a collector row' % (role, name))
            return
        if facts.get('pid') != pid:
            reasons.add('process_identity_changed', EVIDENCE, '%s pid %s, expected %s' % (role, facts.get('pid'), pid))
            return
        if facts.get('start_id') != start_id:
            reasons.add('pid_reused', EVIDENCE, '%s pid %s started at %s, expected %s' % (role, pid, facts.get('start_id'), start_id))
            return
        if boot and row.get('boot_id') != boot:
            reasons.add('host_rebooted', CLOCK, '%s collector boot id %s, expected %s' % (role, row.get('boot_id'), boot))
            return


def socket_series(rows, name):
    series = {}
    for row in rows:
        for item in ((row.get('procs') or {}).get(name) or {}).get('sockets') or ():
            if isinstance(item, dict):
                series.setdefault(item.get('local_port'), []).append(item)
    return series


def check_socket(series, port, label, counters_required, prior_inodes, reasons, category, row_count):
    """One socket, identified by endpoint and inode. Its inode must not change and its counter must not move backward. Returns the drop delta."""
    rows = series.get(port) or []
    if not rows:
        reasons.add('socket_evidence_missing', EVIDENCE, '%s: no socket on port %s' % (label, port))
        return None
    if len(rows) != row_count:
        reasons.add('socket_evidence_missing', EVIDENCE, '%s: the socket is in %d of %d collector rows' % (label, len(rows), row_count))
        return None
    inodes = {row.get('inode') for row in rows}
    if len(inodes) != 1 or not rows[0].get('inode'):
        reasons.add('socket_identity_changed', EVIDENCE, '%s: inodes %s' % (label, sorted(str(i) for i in inodes)))
        return None
    if rows[0]['inode'] in prior_inodes:
        reasons.add('socket_identity_reused', EVIDENCE, '%s: inode %s was used by an earlier run' % (label, rows[0]['inode']))
        return None
    first, last = rows[0].get('drops'), rows[-1].get('drops')
    if first is None and last is None and all(row.get('drops') is None for row in rows):
        if counters_required:
            reasons.add('socket_counters_missing', EVIDENCE, '%s has no kernel drop counter' % label)
        return None
    if not is_count(first) or not is_count(last):
        reasons.add('socket_counters_missing', EVIDENCE, '%s: baseline %r, final %r' % (label, first, last))
        return None
    values = [row.get('drops') for row in rows]
    if any(not is_count(value) for value in values) or any(right < left for left, right in zip(values, values[1:])):
        reasons.add('socket_counter_reset', EVIDENCE, '%s: the drop counter moved backward or vanished' % label)
        return None
    delta = last - first
    if delta and category == GENERATOR:   # a game-socket drop stays a fact for the scorer
        reasons.add('generator_socket_drops', GENERATOR, '%s dropped %d datagrams in the window' % (label, delta))
    return delta


def host_counter_delta(rows):
    """Raw host-wide kernel counters, separate from any socket. They can never attribute a drop to a socket."""
    if len(rows) < 2:
        return None
    first, last = (rows[0].get('udp') or {}).get('snmp'), (rows[-1].get('udp') or {}).get('snmp')
    if not isinstance(first, dict) or not isinstance(last, dict):
        return None
    return {key: last[key] - first[key] for key in sorted(first) if is_int(first.get(key)) and is_int(last.get(key))}


# ---- the proof ------------------------------------------------------------------------------------

def prove(root, trial, workload, identities, brackets, telemetry_schema=None, require_counters=True, allow_short_hold=False, prior=None):
    """``identities``: role to (name to process identity), from the supervisors. ``brackets``: dict(before, after) raw documents.

    ``prior``: role to dict(processes=set of (pid, start_id, boot_id), inodes=set) used by earlier runs on that host.
    """
    root = pathlib.Path(root)
    limits = schema()['limits']
    reasons = Reasons()
    prior = prior or {}
    facts = dict(contract_hold=trial['hold_s'] in schema()['contract_holds_s'], hold_s=trial['hold_s'], target=trial['target'], telemetry_schema_checked=telemetry_schema is not None)
    if telemetry_schema is not None and (telemetry_schema.get('id') != schema()['id'] or telemetry_schema.get('sha256') != schema_sha256()):
        reasons.add('schema_mismatch', EVIDENCE, 'the manifest froze %s %s' % (telemetry_schema.get('id'), telemetry_schema.get('sha256')))
    if not facts['contract_hold'] and not allow_short_hold:
        reasons.add('non_contract_hold', EVIDENCE, 'a %d s hold is not one of the accepted windows' % trial['hold_s'])
    swarm = load_swarm(root, trial, workload, limits, reasons)
    if swarm is None:
        return _document(trial, reasons, facts, require_counters)
    facts['window_bot_mono_ns'] = [swarm['start'], swarm['end']]
    facts['final_auth_bot_mono_ns'] = swarm['final_auth']
    facts['input'] = _input_summary(swarm['offered'], limits)
    facts['per_bot_input'] = swarm['offered']
    facts['shards'] = [dict(bots=shard['expected'], max_poll_gap_ns=shard['max_poll_gap_ns'], polls=shard['polls'], observer_ns=shard['observer_ns']) for shard in swarm['shard_facts']]
    bot_ident = (identities or {}).get('bot') or {}
    game_ident = (identities or {}).get('game') or {}
    _check_swarm_identity(swarm, bot_ident.get('bot'), reasons)
    game = load_game(root, reasons, limits)
    if game is not None:
        _check_game_identity(game, game_ident.get('game'), reasons)
    mapping = _map_interval(swarm, game, brackets, limits, reasons, facts)
    if mapping is not None and game is not None and 'game_mono' in mapping:
        facts['population'] = check_population(game, swarm, mapping['game_mono'], mapping['game_core'], trial, reasons)
    # Each host's own problems are named apart, because a dead game host says nothing about whether the generator's counters were proven.
    mark = len(reasons.items)
    bot_rows = load_sampler(root, 'bot', reasons)
    facts['bot_host'] = _check_bot_host(swarm, bot_rows, bot_ident.get('bot'), prior.get('bot') or {}, require_counters, limits, reasons)
    facts['bot_host_problems'] = sorted({item['code'] for item in reasons.items[mark:]})
    mark = len(reasons.items)
    game_rows = load_sampler(root, 'game', reasons)
    facts['game_host'] = _check_game_host(mapping, game_rows, game_ident.get('game'), prior.get('game') or {}, require_counters, limits, reasons)
    facts['game_host_problems'] = sorted({item['code'] for item in reasons.items[mark:]})
    return _document(trial, reasons, facts, require_counters)


def _document(trial, reasons, facts, require_counters):
    return dict(schema=PROOF_SCHEMA, measurement_schema=schema()['id'], measurement_schema_sha256=schema_sha256(), run_id=trial.get('run_id'), status=reasons.status(), reasons=reasons.items,
                facts=facts, socket_counters_required=require_counters, establishes_capacity=False)


def _input_summary(offered, limits):
    if not offered:
        return None
    worst = min(offered, key=lambda row: row['ratio'])
    return dict(bots=len(offered), scheduled_total=sum(row['scheduled'] for row in offered), sent_total=sum(row['sent'] for row in offered), worst_bot=worst['bot'], worst_ratio=worst['ratio'],
                below_minimum=[row['bot'] for row in offered if row['sent'] * 100 < row['scheduled'] * limits['input_min_percent']], peer_samples_total=sum(row['peer_samples'] for row in offered),
                peer_samples_min=min(row['peer_samples'] for row in offered), dead_frames_total=sum(row.get('dead_frames') or 0 for row in offered))


def _check_swarm_identity(swarm, expected, reasons):
    document = swarm['swarm']
    if not expected:
        reasons.add('identity_missing', EVIDENCE, 'no supervisor identity for the swarm')
        return
    if document.get('pid') != expected.get('pid'):
        reasons.add('recorder_overwritten', EVIDENCE, 'swarm.json came from pid %s, the supervisor started %s' % (document.get('pid'), expected.get('pid')))
    if document.get('kernel_start_id') and document['kernel_start_id'] != expected.get('start_id'):
        reasons.add('pid_reused', EVIDENCE, 'swarm.json was written by pid %s with another start time' % document.get('pid'))


def _check_game_identity(game, expected, reasons):
    process = game['process']
    if not expected:
        reasons.add('identity_missing', EVIDENCE, 'no supervisor identity for the game')
        return
    if process.get('pid') != expected.get('pid'):
        reasons.add('recorder_overwritten', EVIDENCE, 'telemetry came from pid %s, the supervisor started %s' % (process.get('pid'), expected.get('pid')))
    if process.get('kernel_start_id') and process['kernel_start_id'] != expected.get('start_id'):
        reasons.add('pid_reused', EVIDENCE, 'telemetry was written by pid %s with another start time' % process.get('pid'))


def _map_interval(swarm, game, brackets, limits, reasons, facts):
    """Bot monotonic boundaries to conservative wall and game-monotonic intervals. Any failure here leaves the interval unprovable."""
    bot_domain = swarm['domain']
    for domain in [bot_domain] + ([game['domain']] if game else []):
        for step in domain.steps():
            reasons.add('clock_step', CLOCK, '%s wall clock jumped %.1f ms' % (domain.name, step['jump_ns'] / 1e6))
    start_wall, end_wall = bot_domain.to_wall(swarm['start']), bot_domain.to_wall(swarm['end'])
    if start_wall is None or end_wall is None:
        reasons.add('clock_mapping_missing', CLOCK, 'no swarm wall pair near a boundary')
        return None
    mapping = dict(bot_wall=(start_wall[0], end_wall[1]), bot_core_wall=(start_wall[1], end_wall[0]))
    if game is None:
        return mapping
    offset_bot = host_offset(brackets or {}, 'bot', reasons)
    offset_game = host_offset(brackets or {}, 'game', reasons)
    if offset_bot is None or offset_game is None:
        return mapping
    to_game = lambda wall: (wall[0] - offset_bot[1] + offset_game[0], wall[1] - offset_bot[0] + offset_game[1])
    start_game, end_game = to_game(start_wall), to_game(end_wall)
    half_width = max(start_game[1] - start_game[0], end_game[1] - end_game[0]) / 2
    facts['clock'] = dict(boundary_half_width_ms=half_width / 1e6, bot_offset_ns=[offset_bot[0], offset_bot[1]], game_offset_ns=[offset_game[0], offset_game[1]])
    if half_width > limits['clock_max_half_width_ms'] * 1_000_000:
        reasons.add('clock_ambiguous', CLOCK, 'a boundary is known only to +/-%.0f ms' % (half_width / 1e6))
    start_mono = game['domain'].to_mono(*start_game)
    end_mono = game['domain'].to_mono(*end_game)
    if start_mono is None or end_mono is None:
        reasons.add('clock_mapping_missing', CLOCK, 'no server wall pair near a mapped boundary')
        return mapping
    mapping.update(game_wall=(start_game[0], end_game[1]), game_mono=(start_mono[0], end_mono[1]), game_core=(start_mono[1], end_mono[0]))
    facts['clock'].update(game_wall_ns=list(mapping['game_wall']), game_core_wall_ns=[start_game[1], end_game[0]])
    return mapping


def _check_bot_host(swarm, rows, identity, prior, require_counters, limits, reasons):
    start_wall, end_wall = swarm['domain'].to_wall(swarm['start']), swarm['domain'].to_wall(swarm['end'])
    if start_wall is None or end_wall is None:
        return None
    chosen = role_window(rows, start_wall[0], end_wall[1], 'bot', limits, reasons)
    if chosen is None:
        return None
    check_process_identity(chosen, 'bot', 'bot', identity, prior.get('processes') or set(), reasons)
    series = socket_series(chosen, 'bot')
    drops = {}
    missing = []
    for bot in sorted(swarm['ports']):
        port = swarm['ports'][bot]
        delta = check_socket(series, port, 'bot %s' % bot, require_counters, prior.get('inodes') or set(), reasons, GENERATOR, len(chosen))
        if delta is None:
            missing.append(bot)
        else:
            drops[bot] = delta
    return dict(rows=len(chosen), kernel_counters=host_counter_delta(chosen), socket_drops_total=sum(drops.values()) if not missing else None, sockets_with_counters=len(drops), sockets_without_counters=len(missing),
                collector_cost_ns_max=max((row.get('collector_ns') or 0 for row in chosen), default=None))


def _check_game_host(mapping, rows, identity, prior, require_counters, limits, reasons):
    if mapping is None or 'game_wall' not in mapping:
        reasons.add('collector_boundary_missing', EVIDENCE, 'the game interval could not be mapped')
        return None
    chosen = role_window(rows, mapping['game_wall'][0], mapping['game_wall'][1], 'game', limits, reasons)
    if chosen is None:
        return None
    check_process_identity(chosen, 'game', 'game', identity, prior.get('processes') or set(), reasons)
    series = socket_series(chosen, 'game')
    if len(series) != 1:
        reasons.add('socket_evidence_missing', EVIDENCE, 'the game process owns %d UDP sockets in the interval' % len(series))
        return dict(rows=len(chosen), kernel_counters=host_counter_delta(chosen), socket_drops=None)
    port = next(iter(series))
    delta = check_socket(series, port, 'game socket', require_counters, prior.get('inodes') or set(), reasons, SERVER, len(chosen))
    # A game-socket drop is a capacity fact for the scorer, not a broken window.
    return dict(rows=len(chosen), kernel_counters=host_counter_delta(chosen), socket_drops=delta, socket_port=port, socket_inode=series[port][0].get('inode'),
                collector_cost_ns_max=max((row.get('collector_ns') or 0 for row in chosen), default=None))
