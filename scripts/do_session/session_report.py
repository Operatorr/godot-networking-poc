"""What one DigitalOcean session measured, cost and left behind (handoff slice 7, issue #70). Pure over retained files, with no clock and nothing live.

    build(session_dir, inventory, registry, capacity, invoices, publication) -> document
    render(document) -> Markdown
    compact(document, sums) -> the only document that may leave the laptop, built field by field

Three results stay separate and none can stand in for another: what was measured, whether the evidence is complete, and whether the resources are gone. A report renders them and proves nothing by rendering.
A run that cannot be held to its files reads as what it is, and an incomplete inventory withholds every capacity claim: a verdict stays on record as history, and it is not vouched for.

Missing values are ``None``, never zero. Every diagnostic is labelled by the interval it covers: the scored window, or that run's collector span. Bytes are bytes, and a bit rate is named as one. No diagnostic here is a gate.

Money has four separate lines that are never added together: the game tier's nominal monthly price, the admission estimate, a lifetime-based estimate for both hosts and transfer, and whatever invoices were later recorded. The management host is disclosed beside them and is in none of them.
"""
import csv
import json
import math
import pathlib

import admission
import capacity_scorer
import cleanup_provider
import manifest as manifest_mod
import measurement_window as mw
import search
import session_clock

REPORT_SCHEMA = 'omega.do-session.session-report/1'
RUN_SUMMARY_SCHEMA = 'omega.do-session.run-summary/1'
COMPACT_SCHEMA = 'omega.do-session.published-summary/1'
PROVIDER_LABEL = 'DigitalOcean'
SEPARATE_FROM_CAX11 = 'DigitalOcean evidence only. It is not a CAX11 result, satisfies no part of the historical CAX11 gate and shows nothing about ARM versus x86.'
RAW_EVIDENCE_POLICY = 'Raw evidence is never published. The author keeps it privately on one laptop disk (a single copy, by accepted risk) indefinitely, and it is available on request, verifiable against this SHA256 inventory. If that disk is lost, these hashes point at evidence that no longer exists.'
READS_AS_DIAGNOSTIC = 'CPU, memory, gaps, bandwidth and cost are diagnostics and add no gate. ENet loss is a smoothed estimate, not a measured fraction of datagrams dropped.'
NO_INVOICE = 'No provider invoice is on record. Nothing in this report is an invoice.'
ROLES = ('game', 'bot')
NS = 1_000_000_000
LOOPBACK = ('lo', 'lo0')


def _number(value, places=6):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return round(value, places) if isinstance(value, float) else value


def _unrounded(value):
    """A gate reading as the scorer computed it. Rounding could carry a passing value onto a strict limit, so these are never rounded."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _divide(numerator, denominator, places=6):
    if _number(numerator) is None or _number(denominator) is None or denominator == 0:
        return None
    return round(numerator / denominator, places)


def _count(value):
    return value if mw.is_count(value) else None


# ---- what the recorders hold ------------------------------------------------------------------------

def _sampler(run_dir, role):
    try:
        return mw.load_sampler(pathlib.Path(run_dir), role, mw.Reasons())
    except (OSError, ValueError, KeyError, TypeError):
        return []


def _bot_wall(root, mono):
    """Where a swarm monotonic boundary sat on its own host's wall, from the nearest pair the coordinator recorded. A diagnostic only: the proof has already decided the window."""
    best = None
    try:
        lines = (pathlib.Path(root) / 'bot' / 'swarm' / 'coordinator.ndjson').read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            pair = json.loads(line).get('clock')
        except ValueError:
            continue
        if mw.valid_pair(pair) and (best is None or abs(pair['mono_ns'] - mono) < abs(best['mono_ns'] - mono)):
            best = pair
    return None if best is None else best['wall_before_ns'] + mono - best['mono_ns']


def _windows(run_dir, proof):
    """{role: rows whose counters bracket the window}, or no entry when that cannot be said. Whatever they count can only be a wider interval than the real one."""
    facts = (proof or {}).get('facts') or {}
    limits = mw.schema()['limits']
    bounds = {}
    game_wall = (facts.get('clock') or {}).get('game_wall_ns')
    if isinstance(game_wall, list) and len(game_wall) == 2:
        bounds['game'] = game_wall
    window = facts.get('window_bot_mono_ns')
    if isinstance(window, list) and len(window) == 2:
        low, high = _bot_wall(run_dir, window[0]), _bot_wall(run_dir, window[1])
        if low is not None and high is not None:
            bounds['bot'] = [low, high]
    found = {}
    for role, (low, high) in bounds.items():
        try:
            rows = mw.role_window(_sampler(run_dir, role), low, high, role, limits, mw.Reasons())
        except (OSError, ValueError, KeyError, TypeError):
            rows = None
        if rows:
            found[role] = rows
    return found


def _span_s(rows):
    if len(rows) < 2:
        return None
    return (rows[-1]['clock']['mono_ns'] - rows[0]['clock']['mono_ns']) / NS


def _process_cpu(rows, name):
    """100% is one core, as the contract asks."""
    span = _span_s(rows)
    processes = [(row.get('procs') or {}).get(name) or {} for row in rows]
    if not span or not processes:
        return dict(percent_of_one_core=None, rss_max_bytes=None, threads=[])
    first, last = _number(processes[0].get('cpu_s')), _number(processes[-1].get('cpu_s'))
    threads = []
    before, after = processes[0].get('thread_cpu_s'), processes[-1].get('thread_cpu_s')
    if isinstance(before, dict) and isinstance(after, dict):
        for thread in sorted(set(before) & set(after)):
            moved = _number(after[thread]) - _number(before[thread]) if _number(after[thread]) is not None and _number(before[thread]) is not None else None
            threads.append(dict(thread=thread.split('/')[0], percent_of_one_core=_divide(moved * 100 if moved is not None else None, span, 3)))
    rss = [item.get('rss_bytes') for item in processes if mw.is_count(item.get('rss_bytes'))]
    return dict(percent_of_one_core=_divide((last - first) * 100, span, 3) if first is not None and last is not None else None, rss_max_bytes=max(rss) if rss else None, threads=threads)


def _host_cpu(rows):
    first, last = rows[0].get('system') or {}, rows[-1].get('system') or {}
    if not first or not last:
        return dict(utilization_percent=None, steal_percent=None)
    total = _number(last.get('total_s')), _number(first.get('total_s'))
    idle = _number(last.get('idle_s')), _number(first.get('idle_s'))
    steal = _number(last.get('steal_s')), _number(first.get('steal_s'))
    if None in total or total[0] == total[1]:
        return dict(utilization_percent=None, steal_percent=None)
    elapsed = total[0] - total[1]
    return dict(utilization_percent=None if None in idle else _divide((elapsed - (idle[0] - idle[1])) * 100, elapsed, 3), steal_percent=None if None in steal else _divide((steal[0] - steal[1]) * 100, elapsed, 3))


def _memory(rows):
    readings = [row.get('memory') for row in rows if isinstance(row.get('memory'), dict)]
    base = capacity_scorer.memory_diagnostics(rows) or {}
    swap = [item['SwapTotal'] - item['SwapFree'] for item in readings if mw.is_count(item.get('SwapTotal')) and mw.is_count(item.get('SwapFree'))]
    return dict(available_min_bytes=_count(base.get('mem_available_min_bytes')), swap_used_max_bytes=max(swap) if swap else None, host_oom_kill_delta=_count(base.get('host_oom_kill_delta')), major_faults_delta=_count(base.get('pgmajfault_delta')), swapped_out_pages_delta=_count(base.get('pswpout_delta')))


def _interfaces(rows):
    """Bytes in each direction on each interface between two reads. A counter that is absent stays absent."""
    if len(rows) < 2:
        return {}
    first, last = rows[0].get('interfaces'), rows[-1].get('interfaces')
    if not isinstance(first, dict) or not isinstance(last, dict):
        return {}
    found = {}
    for name in sorted(set(first) & set(last)):
        moved = {}
        for field in ('rx_bytes', 'tx_bytes', 'rx_packets', 'tx_packets', 'rx_errs', 'tx_errs', 'rx_drop', 'tx_drop'):
            low, high = first[name].get(field) if isinstance(first[name], dict) else None, last[name].get(field) if isinstance(last[name], dict) else None
            moved[field] = high - low if mw.is_count(low) and mw.is_count(high) and high >= low else None
        found[str(name)] = moved
    return found


def _traffic(rows, players=None):
    """One interval's transfer on one host. Loopback is reported and does not count as transfer."""
    interfaces = _interfaces(rows)
    span = _span_s(rows)
    public = [item for name, item in interfaces.items() if name not in LOOPBACK]
    tx = [item['tx_bytes'] for item in public] if public else []
    rx = [item['rx_bytes'] for item in public] if public else []
    tx_bytes = sum(tx) if tx and None not in tx else None
    rx_bytes = sum(rx) if rx and None not in rx else None
    tx_rate = _divide(tx_bytes, span)
    result = dict(seconds=_number(span, 3), interfaces=interfaces, tx_bytes=tx_bytes, rx_bytes=rx_bytes, tx_bytes_per_s=tx_rate, rx_bytes_per_s=_divide(rx_bytes, span), tx_bits_per_s=_number(tx_rate * 8 if tx_rate is not None else None))
    if players is not None:
        result['tx_bytes_per_s_per_player'] = _divide(tx_bytes, span * players) if span and players else None
        result['rx_bytes_per_s_per_player'] = _divide(rx_bytes, span * players) if span and players else None
    return result


def _host_window(rows, name, players):
    if not rows:
        return dict(covered=False)
    return dict(covered=True, seconds=_number(_span_s(rows), 3), process=_process_cpu(rows, name), host=_host_cpu(rows), memory=_memory(rows), traffic=_traffic(rows, players), kernel_receive_errors=_kernel_counter(rows, 'RcvbufErrors'), kernel_in_errors=_kernel_counter(rows, 'InErrors'))


def _kernel_counter(rows, name):
    """Whole-host, so never attributed to any socket. Kept apart from the socket's own counter."""
    values = [((row.get('udp') or {}).get('snmp') or {}).get(name) for row in rows]
    if not values or not all(mw.is_count(value) for value in values):
        return None
    return values[-1] - values[0]


def _tick_rows(run_dir):
    path = pathlib.Path(run_dir) / 'game' / 'telemetry' / 'ticks.csv'
    try:
        with path.open(newline='') as handle:
            return list(csv.DictReader(handle))
    except (OSError, ValueError, csv.Error):
        return []


def _int_of(row, name):
    try:
        return int(row[name])
    except (KeyError, TypeError, ValueError):
        return None


def _float_of(row, name):
    try:
        value = float(row[name])
    except (KeyError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _tick_diagnostics(run_dir, proof, gates):
    """Over the narrowest interval the clocks allow, with the over-budget counts the gate kept at both extremes."""
    population = ((proof or {}).get('facts') or {}).get('population') or {}
    core = population.get('core_game_mono_ns')
    if not isinstance(core, list) or len(core) != 2:
        return dict(covered=False)
    inside = [row for row in _tick_rows(run_dir) if _int_of(row, 'mono_ns') is not None and core[0] <= _int_of(row, 'mono_ns') <= core[1]]
    work = sorted(value for value in (_int_of(row, 'work_ns') for row in inside) if value is not None)
    if not work:
        return dict(covered=False)
    monos = [_int_of(row, 'mono_ns') for row in inside]
    span = (monos[-1] - monos[0]) / NS if len(monos) > 1 else None
    lags = [value for value in (_float_of(row, 'accumulator_lag_s') for row in inside) if value is not None]
    authenticated = [value for value in (_int_of(row, 'authenticated') for row in inside) if value is not None]
    gate = (gates or {}).get('tick_budget') or {}
    return dict(covered=True, ticks=len(work), p50_work_ns=capacity_scorer.nearest_rank(work, 50), p90_work_ns=capacity_scorer.nearest_rank(work, 90), p95_work_ns=capacity_scorer.nearest_rank(work, 95), p99_work_ns=capacity_scorer.nearest_rank(work, 99), max_work_ns=work[-1], over_budget_at_most=_count(gate.get('over_wide')), over_budget_at_least=_count(gate.get('over_narrow')), achieved_ticks_per_s=_divide(len(work) - 1, span, 3) if span else None,
                accumulator_lag_max_s=_number(max(lags)) if lags else None, authenticated_min=min(authenticated) if authenticated else None, authenticated_max=max(authenticated) if authenticated else None)


def _samples(run_dir):
    rows = []
    try:
        lines = (pathlib.Path(run_dir) / 'game' / 'telemetry' / 'server.ndjson').read_text().splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and mw.is_count(row.get('mono_ns')):
            rows.append(row)
    rows.sort(key=lambda row: row['mono_ns'])
    return rows


def _bracketing(rows, low, high):
    before = [row for row in rows if row['mono_ns'] <= low]
    after = [row for row in rows if row['mono_ns'] >= high]
    return (before[-1], after[0]) if before and after else (None, None)


def _timing_delta(first, last, name):
    """Cumulative buckets between two samples. ``max_ns`` is cumulative on the server's side, so it is the run's maximum and is labelled so."""
    low, high = ((first.get('loop_phases') or {}).get(name) or {}), ((last.get('loop_phases') or {}).get(name) or {})
    count, total = _count(high.get('count')), _count(high.get('total_ns'))
    base, spent = _count(low.get('count')), _count(low.get('total_ns'))
    if None in (count, total, base, spent) or count < base or total < spent:
        return dict(count=None, mean_ns=None, run_max_ns=_count(high.get('max_ns')))
    return dict(count=count - base, mean_ns=_divide(total - spent, count - base, 1), run_max_ns=_count(high.get('max_ns')))


def _array_total(row, name):
    values = row.get(name)
    if not isinstance(values, list) or not all(mw.is_count(value) for value in values):
        return None
    return sum(values)


def _delta(last, first):
    return last - first if last is not None and first is not None and last >= first else None


def _channel_bytes(row, name):
    """Application bytes per channel, as the server counted them before ENet. Not interface bytes."""
    channels = [0, 0, 0]
    values = row.get(name)
    if not isinstance(values, list):
        return None
    for item in values:
        if not (isinstance(item, list) and len(item) == 2 and isinstance(item[1], list) and len(item[1]) == 3 and all(mw.is_count(value) for value in item[1])):
            return None
        channels = [left + right for left, right in zip(channels, item[1])]
    return channels


def _server_diagnostics(run_dir, proof, players):
    """Snapshot-build time, event sends and recipients, and application traffic, all between the two samples around the widest interval."""
    interval = (((proof or {}).get('facts') or {}).get('population') or {}).get('interval_game_mono_ns')
    if not isinstance(interval, list) or len(interval) != 2:
        return dict(covered=False)
    first, last = _bracketing(_samples(run_dir), interval[0], interval[1])
    if first is None:
        return dict(covered=False)
    sends = _delta(_array_total(last, 'event_sends'), _array_total(first, 'event_sends'))
    reliable = _delta(_array_total(last, 'reliable_event_sends'), _array_total(first, 'reliable_event_sends'))
    sources = _delta(_array_total(last, 'source_events'), _array_total(first, 'source_events'))
    seconds = (last['mono_ns'] - first['mono_ns']) / NS
    sent, received = _channel_bytes(first, 'sent_bytes_by_type_channel'), _channel_bytes(last, 'sent_bytes_by_type_channel')
    moved = [high - low for low, high in zip(sent, received)] if sent is not None and received is not None and all(high >= low for low, high in zip(sent, received)) else None
    total = sum(moved) if moved is not None else None
    return dict(covered=True, seconds=_number(seconds, 3), snapshot_build=_timing_delta(first, last, 'snapshot_build'), world_tick=_timing_delta(first, last, 'world_tick'), event_sends=sends, reliable_event_sends=reliable, unreliable_event_sends=sends - reliable if sends is not None and reliable is not None else None,
                source_events=sources, average_recipients=_divide(sends, sources, 3), application_sent_bytes_by_channel=moved, application_sent_bytes_per_s_per_player=_divide(total, seconds * players) if total is not None and players and seconds else None, send_errors_delta=_delta(_count(last.get('send_errors')), _count(first.get('send_errors'))),
                decode_errors_delta=_delta(_count(last.get('decode_errors')), _count(first.get('decode_errors'))))


PEER_PEAK_SCOPE = 'the highest single smoothed reading of any one bot in the window, a diagnostic that decides nothing: the gate reads the per-second mean over bots'


def _peer_diagnostics(gates):
    rtt, loss = (gates or {}).get('rtt_p95') or {}, (gates or {}).get('enet_loss') or {}
    peak = (loss.get('per_second_mean_peak') or {}).get('ratio') or {}
    mean = loss.get('window_mean_of_seconds') or {}
    peer = loss.get('peer_peak') or {}
    return dict(rtt_p95_ms=_number(rtt.get('p95_ms')), rtt_max_ms=_number(rtt.get('max_ms')), rtt_samples=_count(rtt.get('samples')), loss_estimate_peak_per_second_mean=_unrounded(peak.get('approximate')), loss_estimate_window_mean=_unrounded(mean.get('approximate')), loss_estimate_peer_peak=_unrounded((peer.get('ratio') or {}).get('approximate')), loss_estimate_peer_peak_bot=_count(peer.get('bot')), loss_estimate_peer_peak_at_bot_mono_ns=_count(peer.get('at_bot_mono_ns')), loss_estimator='ENet smoothed estimate of reliable commands lost', loss_estimate_peer_peak_scope=PEER_PEAK_SCOPE)


def _socket_diagnostics(proof, score):
    facts = (proof or {}).get('facts') or {}
    game, bot = facts.get('game_host') or {}, facts.get('bot_host') or {}
    gate = ((score or {}).get('gates') or {}).get('game_socket_drops') or {}
    return dict(game_socket_drops=_count(game.get('socket_drops')), game_socket_drops_proven_inside=_count(gate.get('drops_proven_inside')), generator_socket_drops=_count(bot.get('socket_drops')), scope='identified sockets of the supervised processes; kernel counters are reported separately and name nobody')


def _safely(default, function, *arguments):
    """A surprising file costs that one diagnostic, which then reads as unknown. It never costs the report, and nothing here decides anything."""
    try:
        return function(*arguments)
    except capacity_scorer.READ_FAILURES:
        return default


def _offered_diagnostics(score):
    generator = (score or {}).get('offered_load') or {}
    worst = generator.get('worst_ratio')
    return dict(scheduled_frames=_count(generator.get('scheduled_total')), sent_frames=_count(generator.get('sent_total')), worst_bot_ratio=_number(worst.get('approximate')) if isinstance(worst, dict) else None)


TRAJECTORY_SCOPE = 'One entry per held second. These are diagnostics and decide nothing. The Tick series count from the start of the narrowest interval on the server\'s clock and the ENet series from the window start on the bot\'s clock, so one index can differ between them by the clock mapping. An entry with no reading is null.'
TRAJECTORY_SERIES = ('tick_p95_work_ns', 'tick_max_work_ns', 'tick_over_budget', 'rtt_p95_ms', 'loss_estimate_mean')


def _tick_series(run_dir, proof, hold_s):
    """Tick work per held second, over the interval ``_tick_diagnostics`` reads. A wall clock that stepped leaves no interval on the server's clock to trust."""
    if {item.get('code') for item in (proof or {}).get('reasons') or () if isinstance(item, dict)} & capacity_scorer.CLOCK_BREAKING_CODES:
        return None
    core = (((proof or {}).get('facts') or {}).get('population') or {}).get('core_game_mono_ns')
    if not isinstance(core, list) or len(core) != 2:
        return None
    bins = [[] for _ in range(hold_s)]
    for row in _tick_rows(run_dir):
        mono, work = _int_of(row, 'mono_ns'), _int_of(row, 'work_ns')
        if mono is not None and work is not None and core[0] <= mono <= core[1]:
            bins[min(hold_s - 1, (mono - core[0]) // NS)].append(work)
    if not any(bins):
        return None
    ordered = [sorted(item) for item in bins]
    return dict(tick_p95_work_ns=[capacity_scorer.nearest_rank(item, 95) if item else None for item in ordered], tick_max_work_ns=[item[-1] if item else None for item in ordered],
                tick_over_budget=[sum(1 for work in item if work > capacity_scorer.TICK_BUDGET_NS) if item else None for item in ordered])


def _trajectory(run_dir, proof, trial, workload):
    """What the run did second by second. Each side stands alone: losing the Tick record costs the Tick series and not the ENet ones."""
    hold_s = trial.get('hold_s')
    if proof is None or not mw.is_count(hold_s) or not hold_s:
        return dict(covered=False)
    ticks = _safely(None, _tick_series, run_dir, proof, hold_s)
    peers = _safely(None, capacity_scorer.per_second_series, run_dir, trial, workload)
    if ticks is None and peers is None:
        return dict(covered=False)
    found = dict(ticks or {}, **(peers or {}))
    series = {name: [_unrounded(item) for item in found.get(name) or [None] * hold_s] for name in TRAJECTORY_SERIES}
    return dict(covered=True, seconds=hold_s, scope=TRAJECTORY_SCOPE, **series)


def _ratio_of(value):
    return {key: value.get(key) for key in ('exact', 'approximate')} if isinstance(value, dict) else None


def _gate_values(gates):
    """What the gates measured, for the ones the diagnostics do not already carry."""
    tick, continuity, errors = gates.get('tick_budget') or {}, gates.get('continuity') or {}, gates.get('bot_errors') or {}
    counts = [_count(errors.get(name)) for name in capacity_scorer.BOT_ERROR_COUNTS]
    return dict(tick_over_budget_worst_ratio=_ratio_of(tick.get('worst_possible_ratio')), tick_over_budget_least_ratio=_ratio_of(tick.get('least_possible_ratio')), continuity_unexpected_disconnects=_count(continuity.get('unexpected_disconnects_in_window')), bot_errors_total=sum(counts) if None not in counts else None)


def run_diagnostics(run_dir, proof, score, trial, workload=None):
    """Everything the contract asks to see for one trial, from its sealed files. Nothing here reads ``report.json`` as a measurement."""
    players = trial.get('target')
    windows = _safely({}, _windows, run_dir, proof)
    gates = (score or {}).get('gates') or {}
    uncovered = dict(covered=False)
    return dict(requested_players=players, hold_s=trial.get('hold_s'), proof_status=(proof or {}).get('status'), trajectory=_safely(uncovered, _trajectory, run_dir, proof, trial, workload or {}), gate_values=_safely(_gate_values({}), _gate_values, gates), ticks=_safely(uncovered, _tick_diagnostics, run_dir, proof, gates), server=_safely(uncovered, _server_diagnostics, run_dir, proof, players),
                window={role: _safely(uncovered, _host_window, windows.get(role) or [], role, players) for role in ROLES}, run_span_traffic={role: _safely(_traffic([]), _traffic, _sampler(run_dir, role)) for role in ROLES}, peers=_safely(_peer_diagnostics(None), _peer_diagnostics, gates), sockets=_safely(_socket_diagnostics(None, None), _socket_diagnostics, proof, score),
                offered_load=_safely(_offered_diagnostics(None), _offered_diagnostics, score), legacy_whole_run=dict(report_json_present=(pathlib.Path(run_dir) / 'bot' / 'report.json').exists(), decides_nothing=True))


# ---- one run ------------------------------------------------------------------------------------------

def _read(path):
    try:
        document = json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError, RecursionError):
        return None
    return document if isinstance(document, dict) else None


def run_row(session_dir, row, roles, controller_problems=()):
    """One trial: what the journal said, whether its files hold up, and what they show. ``row`` is one row of ``capacity_report.build``, which already held the verdict to its files. ``controller_problems`` is what the inventory found missing of the controller's own inputs for it, which a verdict that still verifies does not answer."""
    run_dir = pathlib.Path(session_dir) / 'runs' / row['run_id']
    proof = _read(run_dir / 'window-proof.json')
    score = _read(run_dir / capacity_scorer.SCORE_FILE) if row.get('score_sha256') is not None and not row.get('evidence_problems') else None
    trial = dict(run_id=row['run_id'], phase=row['phase'], target=row['target'], repetition=row['repetition'], hold_s=row['hold_s'])
    return dict(trial, ordinal=row['ordinal'], outcome=row['outcome'], classification=row.get('classification'), reasons=list(row.get('reasons') or ()), offered_load=row.get('offered_load'), gates=dict(row.get('gates') or {}), gate_values=dict(row.get('values') or {}),
                proof_reason_codes=sorted({str(item.get('code')) for item in (proof or {}).get('reasons') or () if isinstance(item, dict)}), evidence_problems=list(row.get('evidence_problems') or ()) + list(controller_problems), hard_facts=[dict(outcome=fact.get('outcome'), record=fact.get('record')) for fact in row.get('hard_facts') or ()],
                superseded_decisions=[dict(file=item.get('file'), outcome=item.get('outcome')) for item in row.get('superseded_decisions') or ()], unverified_stop_records=[dict(record=item.get('record'), sha256=item.get('sha256')) for item in row.get('unverified_stop_records') or ()],
                evidence_roles=roles, verified=row.get('outcome') is not None and not row.get('evidence_problems') and not controller_problems and all(item['status'] == 'verified' and not item.get('required_absent') for item in roles.values()), diagnostics=run_diagnostics(run_dir, proof, score, trial, (_read(pathlib.Path(session_dir) / 'manifest.json') or {}).get('workload')))


def run_summary(session_dir, row, roles, controller_problems=()):
    """``runs/<run_id>/summary.json``. Only this run's own retained files."""
    return dict(schema=RUN_SUMMARY_SCHEMA, provider=PROVIDER_LABEL, separate_from_cax11=SEPARATE_FROM_CAX11, **run_row(session_dir, row, roles, controller_problems))


def render_run(summary):
    lines = ['# %s run: %s' % (PROVIDER_LABEL, summary['run_id']), '', '%s target %s, hold %s s, repetition %s. Outcome **%s** (%s). A single run establishes no capacity.' % (summary['phase'], summary['target'], summary['hold_s'], summary['repetition'], summary['outcome'] or 'pending', summary['classification'] or 'no standing score'), '']
    lines += ['- Not verified: ' + item for item in summary['evidence_problems']]
    for role, item in sorted(summary['evidence_roles'].items()):
        lines.append('- %s evidence: %s' % (role, _role_line(item)))
    lines += ['', _diagnostic_table([summary]), '', SEPARATE_FROM_CAX11, READS_AS_DIAGNOSTIC, '']
    return '\n'.join(lines)


def _role_line(item):
    parts = [item['status']]
    if item.get('required_absent'):
        parts.append('required files absent: ' + ', '.join(item['required_absent']))
    if item.get('partial_retained'):
        parts.append('%d partial file(s) retained' % len(item['partial_retained']))
    if item.get('problems'):
        parts.append('; '.join(item['problems']))
    return '; '.join(parts)


# ---- the session --------------------------------------------------------------------------------------

def _event_times(registry):
    found = {}
    for event in (registry or {}).get('journal') or ():
        if isinstance(event, dict):
            found.setdefault(event.get('kind'), []).append(event)
    return found


def _resume_history(session_dir):
    history = []
    try:
        lines = (pathlib.Path(session_dir) / 'execution' / 'journal.ndjson').read_text().splitlines()
    except OSError:
        return history
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get('kind') == 'resume_request':
            history.append(dict(at=row.get('at'), decision=row.get('decision'), code=row.get('code'), fencing_token=row.get('fencing_token'), operator_request_ref=row.get('operator_request_ref')))
    return history


def _cleanup_receipt(registry):
    """What the registry can say about deletion, with nothing inferred. No reading of it is no claim about it."""
    status = (registry or {}).get('status')
    if not isinstance(status, dict):
        return dict(known=False, outcome=None, verified_absent=False, statement='The registry could not be read when this was written, so nothing is said about the resources.')
    cleanup = status.get('cleanup') or {}
    resources = [dict(kind=item.get('kind'), provider_id=item.get('provider_id'), status=item.get('status'), attempts=item.get('attempts'), verified_absent_at=item.get('verified_absent_at'), last_error=cleanup_provider.redact(item['last_error']) if item.get('last_error') else None) for item in status.get('resources') or ()]
    incidents = [dict(kind=item.get('kind'), status=item.get('status'), opened_at=item.get('opened_at'), resolved_at=item.get('resolved_at'), overrun_s=item.get('overrun_s')) for item in status.get('incidents') or ()]
    verified = status.get('overall') in ('clean', 'resources_verified_evidence_incomplete', 'resources_verified_after_overdue', 'resources_verified_with_operator_disposition')
    return dict(known=True, outcome=cleanup.get('outcome'), requested_at=cleanup.get('requested_at'), reason=cleanup_provider.redact(cleanup.get('reason')) if cleanup.get('reason') else None, verified_at=cleanup.get('verified_at'), verified_absent=bool(verified and not cleanup.get('unresolved_creates') and cleanup.get('verified_at')),
                overrun_s=cleanup.get('overrun_s'), overrun_is_lower_bound=cleanup.get('overrun_is_lower_bound'), overdue=cleanup.get('overdue'), unresolved_creates=len(cleanup.get('unresolved_creates') or ()), overall=status.get('overall'), deadlines=dict(t0_utc=status.get('t0_utc'), cleanup_c_utc=status.get('cleanup_c_utc'), deadline_d_utc=status.get('deadline_d_utc')),
                resources=resources, incidents=incidents, statement=_cleanup_statement(verified, cleanup, incidents))


def _cleanup_statement(verified, cleanup, incidents):
    if not cleanup.get('requested_at') and not verified:
        return 'Cleanup has not been requested yet. The watchdog still deletes by C with or without this controller.'
    if not verified or not cleanup.get('verified_at'):
        return 'Deletion is not verified. An accepted delete, a stopped process or a failed read is not proof of destruction.'
    if cleanup.get('unresolved_creates'):
        return 'Deletion is not verified: a create request is still unresolved.'
    return 'Every owned resource was verified absent through authenticated provider reads%s.' % (' after a cleanup-overdue incident, which stays on record' if any(item.get('kind') == 'cleanup-overdue' for item in incidents) else '')


def _lifetime(cleanup, status):
    """From the first create to verified absence. Without verification this is only a lower bound, up to what is on record."""
    start, verified = (status or {}).get('t0_utc'), cleanup.get('verified_at')
    if not start:
        return dict(seconds=None, basis='no t0 on record')
    if not verified:
        return dict(seconds=None, basis='deletion is not verified, so the lifetime is not known and the duration cap applies')
    return dict(seconds=session_clock.parse(verified) - session_clock.parse(start), basis='t0 to verified absence')


def _host_transfer(rows_by_run):
    """The highest reading of each host's own interface counters, since its boot. It stops at the last collector read, so it is a lower bound."""
    totals = {}
    for role in ROLES:
        interfaces = {}
        for rows in rows_by_run:
            last = next((row.get('interfaces') for row in reversed(rows.get(role) or ()) if isinstance(row.get('interfaces'), dict)), None)
            for name, item in (last or {}).items():
                if name not in LOOPBACK and isinstance(item, dict) and mw.is_count(item.get('tx_bytes')):
                    interfaces[name] = max(interfaces.get(name, 0), item['tx_bytes'])
        totals[role] = sum(interfaces.values()) if interfaces else None
    return totals


def economics(manifest, claim, lifetime, measured_tx, invoices):
    """Four lines that are never added together. A players-per-dollar figure exists only for a confirmed claim."""
    pricing, quote = manifest['pricing'], manifest['quote']
    condition = manifest['session']['condition']
    nominal = condition.get('nominal_monthly_usd')
    observed = claim.get('players') if claim.get('players') is not None else claim.get('lower_bound')
    per_dollar = _divide(observed, nominal, 3) if claim.get('confirmed') and observed is not None else None
    hosts = {}
    for role in ROLES:
        item = quote['roles'][role]
        seconds = lifetime['seconds']
        units = admission._billable_units(seconds, pricing) if seconds is not None else None
        compute = round(units * item['price_hourly_usd'] * pricing['billing_increment_s'] / 3600.0, 6) if units is not None else None
        allowance = None
        if seconds is not None:
            allowance = item['transfer_tib_month'] * 1024.0 * (seconds / 3600.0) / pricing['allowance_hours_per_month'] if pricing['prorate_transfer_allowance'] else 0.0
        tx = measured_tx.get(role)
        tx_gib = round(tx / 1024 ** 3, 6) if tx is not None else None
        overage = max(0.0, tx_gib - allowance) if tx_gib is not None and allowance is not None else None
        hosts[role] = dict(size_slug=item['size_slug'], price_hourly_usd=item['price_hourly_usd'], billable_units=units, compute_usd=compute, measured_outbound_bytes_lower_bound=tx, measured_outbound_gib_lower_bound=tx_gib, prorated_allowance_gib=round(allowance, 6) if allowance is not None else None, transfer_overage_usd=round(overage * pricing['transfer_overage_usd_per_gib'], 6) if overage is not None else None)
    compute_values, transfer_values = [host['compute_usd'] for host in hosts.values()], [host['transfer_overage_usd'] for host in hosts.values()]
    estimated = round(sum(compute_values) + sum(transfer_values), 6) if None not in compute_values and None not in transfer_values else None
    planned = admission.estimate_cost(manifest)
    return dict(nominal_game_tier=dict(monthly_usd=nominal, display=condition.get('display'), confirmed_players=observed if claim.get('confirmed') else None, players_per_monthly_game_usd=per_dollar, is_lower_bound=bool(claim.get('search_cap_reached')), meaning='The game host\'s nominal monthly list price only. The bot host, transfer and this test are not in it.'),
                session_estimate=dict(label='estimate, not an invoice', quote_observed_at=quote.get('observed_at'), lifetime_s=_number(lifetime['seconds'], 3), lifetime_basis=lifetime['basis'], hosts=hosts, total_estimated_usd=estimated, assumptions=['both hosts, billed by the manifest\'s increment and minimum', 'measured outbound stops at the last collector read, so transfer is a lower bound', 'a short-lived host does not get a whole month\'s allowance']),
                admission_estimate=dict(label='what admission reserved for the full duration cap, not what was spent', session_estimate_usd=planned['session_estimate_usd'], max_estimated_session_usd=planned['max_estimated_session_usd'], compute_usd=planned['compute_usd'], transfer_usd=planned['transfer_usd']),
                management_host=dict(label='disclosed separately, and in none of the above', monthly_usd=pricing.get('management_host_monthly_usd')), invoices=dict(recorded=list(invoices or ()), statement=NO_INVOICE if not invoices else 'Provider billing as recorded later by the operator. It is kept apart from every estimate here.'))


def _confirmations(rows):
    confirm = [row for row in rows if row['phase'] == search.CONFIRM]
    numbers = []
    for row in confirm:
        ticks, peers = row['diagnostics']['ticks'], row['diagnostics']['peers']
        numbers.append(dict(run_id=row['run_id'], outcome=row['outcome'], tick_p95_work_ns=ticks.get('p95_work_ns'), tick_max_work_ns=ticks.get('max_work_ns'), rtt_p95_ms=peers['rtt_p95_ms'], loss_estimate_peak=peers['loss_estimate_peak_per_second_mean'], loss_estimate_peer_peak=peers['loss_estimate_peer_peak']))
    spread = {}
    for key in ('tick_p95_work_ns', 'tick_max_work_ns', 'rtt_p95_ms', 'loss_estimate_peak', 'loss_estimate_peer_peak'):
        values = [item[key] for item in numbers if item[key] is not None]
        spread[key] = dict(low=min(values), high=max(values), of=len(values)) if values else None
    return dict(runs=numbers, spread=spread)


def build(session_dir, inventory, registry, capacity, invoices=(), publication=None):
    """The whole document, from what was written down. No value in it comes from a clock or a host."""
    session_dir = pathlib.Path(session_dir)
    manifest = json.loads((session_dir / 'manifest.json').read_text())
    roles_by_run = {}
    for entry in inventory.get('roles') or ():
        roles_by_run.setdefault(entry['run_id'], {})[entry['role']] = {key: entry.get(key) for key in ('status', 'required_absent', 'partial_retained', 'problems')}
    controller = inventory.get('controller_inputs') or {}
    rows = [run_row(session_dir, row, roles_by_run.get(row['run_id'], {}), (controller.get('by_run') or {}).get(row['run_id'], ())) for row in capacity['trials']]
    status = (registry or {}).get('status') if isinstance((registry or {}).get('status'), dict) else None
    evidence_status = inventory.get('status')
    claim = dict(capacity['claim'])
    withheld = None
    if evidence_status != 'complete' and claim.get('confirmed'):
        withheld = claim
        claim = dict(kind='evidence_incomplete', players=None, lower_bound=None, search_cap_reached=False, confirmed=False, statement='No claim stands while the evidence inventory is %s. What the search recorded is kept apart as history.' % evidence_status)
    cleanup = _cleanup_receipt(registry)
    lifetime = _lifetime(cleanup, status)
    samples = [{role: _sampler(session_dir / 'runs' / row['run_id'], role) for role in ROLES} for row in rows]
    events = _event_times(registry)
    recovery = [dict(first_failure=event['data'].get('first_failure'), deadline=event['data'].get('deadline')) for event in events.get('evidence_recovery') or () if isinstance(event.get('data'), dict)]
    measurement = dict(search_status=capacity.get('status'), claim=claim, journal_claim_withheld=withheld or (capacity.get('journal_claim') if capacity['evidence']['disputed_trials'] else None), evidence_verified_by_report=capacity['evidence'].get('verified'), disputed_trials=list(capacity['evidence']['disputed_trials']), superseded_trials=list(capacity['evidence']['superseded_trials']), recorded_measurement=(status or {}).get('measurement'))
    return dict(schema=REPORT_SCHEMA, provider=PROVIDER_LABEL, label=manifest['session']['condition']['name'], session_id=manifest['session']['id'], separate_from_cax11=SEPARATE_FROM_CAX11, establishes=bool(claim.get('confirmed')), as_of=(registry or {}).get('as_of'), kind=manifest['session'].get('kind'),
                results=dict(measurement=measurement, evidence=dict(status=evidence_status, problems=list(inventory.get('problems') or ()), files=inventory.get('file_count'), bytes=inventory.get('total_bytes'), roles=len(inventory.get('roles') or ()), required_session_missing=list(inventory.get('required_session_missing') or ()), controller_inputs_missing=list(controller.get('missing') or ()), controller_inputs_corrupt=list(controller.get('corrupt') or ()), not_inventoried=[dict(item) for item in inventory.get('not_inventoried') or ()], partial_files=len(inventory.get('partial_files') or ()), corrupt_files=len(inventory.get('corrupt_files') or ())), cleanup=cleanup),
                condition=dict(region=manifest['roles']['game'].get('region'), public_route=manifest['roles']['game'].get('public_route'), game=_role_condition(manifest, 'game'), bot=_role_condition(manifest, 'bot'), workload=manifest.get('workload'), telemetry_schema=manifest.get('telemetry_schema')), source=dict(manifest.get('source') or {}), manifest_sha256=inventory.get('manifest_sha256'),
                records=dict(admissions=inventory.get('admissions'), resume_history=_resume_history(session_dir), recovery_episode=recovery[0] if recovery else None, fencing_tokens=sorted({event['data'].get('token') for event in events.get('control_acquired') or () if isinstance(event.get('data'), dict) and event['data'].get('token') is not None}), registry_journal=(registry or {}).get('verify_journal')),
                runs=rows, confirmations=_confirmations(rows), economics=economics(manifest, claim, lifetime, _host_transfer(samples), invoices), publication=publication or dict(status='not_published'), raw_evidence=dict(policy=RAW_EVIDENCE_POLICY, inventory_sha256=inventory.get('sums_sha256')))


def _role_condition(manifest, role):
    item = manifest['roles'][role]
    return {key: item.get(key) for key in ('size_slug', 'cpu_class', 'vcpus', 'memory_mib', 'disk_gib', 'architecture', 'region', 'image_id')}


# ---- rendering ----------------------------------------------------------------------------------------

def _cell(value):
    return 'unknown' if value is None else str(value).replace('|', '/').replace('\n', ' ')


def _nested(row, *path):
    for key in path:
        row = row.get(key) if isinstance(row, dict) else None
    return row


def _peer_peak_cell(peers):
    return 'unknown' if peers.get('loss_estimate_peer_peak') is None else '%s (bot %s)' % (_cell(peers['loss_estimate_peer_peak']), _cell(peers.get('loss_estimate_peer_peak_bot')))


def _diagnostic_table(rows):
    lines = ['| Run | Tick p95 (ns) | Tick max (ns) | Over budget | Ticks/s | Lag max (s) | Snapshot build mean (ns) | Events (rel / unrel) | Avg recipients | RTT p95 (ms) | Loss est. per-second mean peak | Loss est. peer peak (bot) | Game CPU %core | Host util % | Steal % | Mem avail min (B) | Swap max (B) | Game sock drops | Gen sock drops | Host RcvbufErrors |',
             '| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for row in rows:
        value = row['diagnostics']
        ticks, server, game = value['ticks'], value['server'], value['window']['game']
        lines.append('| %s |' % ' | '.join(_cell(item) for item in (
            row['run_id'], ticks.get('p95_work_ns'), ticks.get('max_work_ns'), '%s..%s' % (_cell(ticks.get('over_budget_at_least')), _cell(ticks.get('over_budget_at_most'))), ticks.get('achieved_ticks_per_s'), ticks.get('accumulator_lag_max_s'), _nested(server, 'snapshot_build', 'mean_ns'), '%s / %s' % (_cell(server.get('reliable_event_sends')), _cell(server.get('unreliable_event_sends'))), server.get('average_recipients'),
            value['peers']['rtt_p95_ms'], value['peers']['loss_estimate_peak_per_second_mean'], _peer_peak_cell(value['peers']), _nested(game, 'process', 'percent_of_one_core'), _nested(game, 'host', 'utilization_percent'), _nested(game, 'host', 'steal_percent'), _nested(game, 'memory', 'available_min_bytes'), _nested(game, 'memory', 'swap_used_max_bytes'), value['sockets']['game_socket_drops'], value['sockets']['generator_socket_drops'], game.get('kernel_receive_errors'))))
    return '\n'.join(lines)


def _traffic_table(rows):
    lines = ['| Run | Game tx window B/s/player | Game tx window bits/s | Game tx window B | Game tx run span B | Bot tx window B | Bot tx run span B | App sent B/s/player |', '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for row in rows:
        value = row['diagnostics']
        game, bot = _nested(value, 'window', 'game', 'traffic') or {}, _nested(value, 'window', 'bot', 'traffic') or {}
        lines.append('| %s |' % ' | '.join(_cell(item) for item in (row['run_id'], game.get('tx_bytes_per_s_per_player'), game.get('tx_bits_per_s'), game.get('tx_bytes'), value['run_span_traffic']['game']['tx_bytes'], bot.get('tx_bytes'), value['run_span_traffic']['bot']['tx_bytes'], value['server'].get('application_sent_bytes_per_s_per_player'))))
    return '\n'.join(lines)


def _cost_lines(economy):
    nominal, session, planned, management, invoices = (economy[key] for key in ('nominal_game_tier', 'session_estimate', 'admission_estimate', 'management_host', 'invoices'))
    lines = ['- **Nominal game tier:** $%s/month %s. Confirmed players per monthly game-host dollar: %s%s. %s' % (_cell(nominal['monthly_usd']), _cell(nominal['display']), _cell(nominal['players_per_monthly_game_usd']), ' (lower bound: search cap)' if nominal['is_lower_bound'] else '', nominal['meaning']),
             '- **Session estimate, not an invoice (both hosts, compute plus transfer):** %s USD over %s s (%s).' % (_cell(session['total_estimated_usd']), _cell(session['lifetime_s']), session['lifetime_basis'])]
    for role in ROLES:
        host = session['hosts'][role]
        lines.append('  - %s `%s`: compute %s USD; outbound %s bytes, lower bound (%s GiB); prorated allowance %s GiB; overage %s USD.' % (role, host['size_slug'], _cell(host['compute_usd']), _cell(host['measured_outbound_bytes_lower_bound']), _cell(host['measured_outbound_gib_lower_bound']), _cell(host['prorated_allowance_gib']), _cell(host['transfer_overage_usd'])))
    lines.append('- **Admission estimate:** %s USD against a limit of %s USD: %s.' % (_cell(planned['session_estimate_usd']), _cell(planned['max_estimated_session_usd']), planned['label']))
    lines.append('- **Management host:** $%s/month, %s.' % (_cell(management['monthly_usd']), management['label']))
    lines.append('- **Invoices:** ' + invoices['statement'])
    for item in invoices['recorded']:
        lines.append('  - %s: %s USD for %s (%s).' % (_cell(item.get('recorded_at')), _cell(item.get('amount_usd')), _cell(item.get('period')), _cell(item.get('source'))))
    return lines


def render(document):
    results = document['results']
    measurement, evidence, cleanup = results['measurement'], results['evidence'], results['cleanup']
    condition = document['condition']
    lines = ['# %s test session: %s' % (document['provider'], document['label']), '', '**%s**' % measurement['claim']['statement'], '', document['separate_from_cax11'], '', 'Rendering this report proves nothing. As of `%s`, from retained files only.' % _cell(document['as_of']), '', '## Three independent results', '',
             '| Result | Status |', '| --- | --- |', '| Measurement | `%s` |' % _cell(measurement['search_status']), '| Evidence | `%s` |' % _cell(evidence['status']), '| Cleanup | `%s` |' % _cell(cleanup.get('overall') or cleanup.get('outcome')), '']
    if measurement['journal_claim_withheld']:
        lines += ['**History, not vouched for:** %s' % measurement['journal_claim_withheld']['statement'], '']
    lines += ['- Not complete: ' + item for item in evidence['problems']]
    lines += ['- Not in this inventory: %s `%s` (%s).' % (item['kind'], item['path'], item['reason']) for item in evidence['not_inventoried']]
    lines += ['- Cleanup: ' + cleanup['statement']]
    if cleanup.get('overrun_s') is not None or cleanup.get('overdue'):
        lines.append('- Cleanup overran D by %s s%s.' % (_cell(cleanup.get('overrun_s')), ' at least' if cleanup.get('overrun_is_lower_bound') else ''))
    for item in cleanup.get('incidents') or ():
        lines.append('- Incident on record: %s, %s, opened %s, resolved %s, overrun %s s.' % (_cell(item['kind']), _cell(item['status']), _cell(item['opened_at']), _cell(item['resolved_at']), _cell(item['overrun_s'])))
    lines += ['', '## Condition', '', '- Region `%s`, route `%s`.' % (_cell(condition['region']), _cell(condition['public_route']))]
    for role in ROLES:
        item = condition[role]
        lines.append('- %s: `%s`, %s vCPU, %s MiB, %s, image `%s`.' % (role, _cell(item['size_slug']), _cell(item['vcpus']), _cell(item['memory_mib']), _cell(item['architecture']), _cell(item['image_id'])))
    source = document['source']
    lines += ['- Source `%s`, controller `%s`, adapter `%s`; manifest `%s`.' % (_cell(source.get('benchmark_sha')), _cell(source.get('controller_sha')), _cell(source.get('adapter_sha')), _cell(document['manifest_sha256'])), '', '## Every trial', '', '| # | Phase | Target | Rep | Hold (s) | Outcome | Offered load | Continuity | Errors | Ticks | Game socket | RTT p95 | ENet loss | Verified |', '| ---: | --- | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for row in document['runs']:
        gates = row['gates']
        lines.append('| %d | %s | %d | %d | %d | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (row['ordinal'], row['phase'], row['target'], row['repetition'], row['hold_s'], row['outcome'] or 'pending', row['offered_load'] or 'no score', *[gates.get(name, 'no score') for name in capacity_scorer.GATE_NAMES], 'yes' if row['verified'] else 'no'))
    for row in document['runs']:
        notes = ['- Evidence %s: %s' % (role, _role_line(item)) for role, item in sorted(row['evidence_roles'].items()) if item['status'] != 'verified' or item.get('required_absent') or item.get('partial_retained')]
        notes += ['- Not verified: ' + item for item in row['evidence_problems']]
        notes += ['- Stop fact %s (%s).' % (item['outcome'], item['record']) for item in row['hard_facts']]
        notes += ['- ' + str(item) for item in row['reasons']]
        if notes:
            lines += ['', '**%s**' % row['run_id']] + notes
    lines += ['', '## Diagnostics over each scored window', '', _diagnostic_table(document['runs']), '', '## Traffic: the scored window against each run\'s collector span', '', 'Bytes unless a column says bits. Loopback is excluded. Window figures count between the reads that bracket the window, so they can only cover a wider interval than it. Run-span figures include ramp and drain and are not comparable with a steady rate.', '', _traffic_table(document['runs']), '', '## Confirmations, individually and as a range', '']
    if document['confirmations']['runs']:
        lines += ['- %s: %s, Tick p95 %s ns, max %s ns, RTT p95 %s ms, loss estimate per-second mean peak %s, peer peak %s.' % (item['run_id'], item['outcome'], _cell(item['tick_p95_work_ns']), _cell(item['tick_max_work_ns']), _cell(item['rtt_p95_ms']), _cell(item['loss_estimate_peak']), _cell(item['loss_estimate_peer_peak'])) for item in document['confirmations']['runs']]
    else:
        lines.append('No confirmation run.')
    lines += ['', '## Cost', ''] + _cost_lines(document['economics']) + ['', '## Evidence and publication', '', '- %s files, %s bytes under this session directory; inventory `%s`.' % (_cell(evidence['files']), _cell(evidence['bytes']), _cell(document['raw_evidence']['inventory_sha256'])), '- Publication: `%s`. %s' % (_cell(document['publication'].get('status')), _cell(document['publication'].get('statement') or 'Nothing is on record as published.')), '- ' + document['raw_evidence']['policy'], '', READS_AS_DIAGNOSTIC, '']
    return '\n'.join(lines)


# ---- what may leave the laptop ------------------------------------------------------------------------

def _safe_text(value):
    return None if value is None else str(value)


def _compact_run(row):
    value = row['diagnostics']
    ticks, server = value['ticks'], value['server']
    game, bot = value['window']['game'], value['window']['bot']
    game_traffic, bot_traffic = game.get('traffic') or {}, bot.get('traffic') or {}
    return dict(run_id=row['run_id'], ordinal=row['ordinal'], phase=row['phase'], target=row['target'], repetition=row['repetition'], hold_s=row['hold_s'], outcome=row['outcome'], classification=row['classification'], offered_load=row['offered_load'], gates={name: row['gates'].get(name) for name in capacity_scorer.GATE_NAMES}, verified=row['verified'], evidence={role: item['status'] for role, item in sorted(row['evidence_roles'].items())}, required_files_absent=sum(len(item.get('required_absent') or ()) for item in row['evidence_roles'].values()),
                not_verified_reasons=len(row['evidence_problems']), proof_reason_codes=[code for code in row['proof_reason_codes'] if code.replace('_', '').isalnum()], gate_values=dict(value['gate_values']), trajectory=dict(value['trajectory']), ticks=dict(p50_work_ns=ticks.get('p50_work_ns'), p90_work_ns=ticks.get('p90_work_ns'), p95_work_ns=ticks.get('p95_work_ns'), p99_work_ns=ticks.get('p99_work_ns'), max_work_ns=ticks.get('max_work_ns'), over_budget_at_most=ticks.get('over_budget_at_most'), over_budget_at_least=ticks.get('over_budget_at_least'), achieved_per_s=ticks.get('achieved_ticks_per_s'), lag_max_s=ticks.get('accumulator_lag_max_s'), count=ticks.get('ticks')),
                snapshot_build_mean_ns=_nested(server, 'snapshot_build', 'mean_ns'), reliable_event_sends=server.get('reliable_event_sends'), unreliable_event_sends=server.get('unreliable_event_sends'), source_events=server.get('source_events'), average_recipients=server.get('average_recipients'), peers={key: value['peers'][key] for key in ('rtt_p95_ms', 'rtt_max_ms', 'rtt_samples', 'loss_estimate_peak_per_second_mean', 'loss_estimate_window_mean', 'loss_estimate_peer_peak', 'loss_estimate_peer_peak_bot', 'loss_estimate_peer_peak_at_bot_mono_ns', 'loss_estimator', 'loss_estimate_peer_peak_scope')},
                game_cpu_percent_of_one_core=_nested(game, 'process', 'percent_of_one_core'), generator_thread_cpu_percent_of_one_core=[item['percent_of_one_core'] for item in _nested(bot, 'process', 'threads') or ()], host_utilization_percent=_nested(game, 'host', 'utilization_percent'), host_steal_percent=_nested(game, 'host', 'steal_percent'), memory_available_min_bytes=_nested(game, 'memory', 'available_min_bytes'), swap_used_max_bytes=_nested(game, 'memory', 'swap_used_max_bytes'), oom_kill_delta=_nested(game, 'memory', 'host_oom_kill_delta'),
                game_socket_drops=value['sockets']['game_socket_drops'], generator_socket_drops=value['sockets']['generator_socket_drops'], kernel_receive_errors=game.get('kernel_receive_errors'), window_traffic=dict(game_tx_bytes=game_traffic.get('tx_bytes'), game_tx_bytes_per_s_per_player=game_traffic.get('tx_bytes_per_s_per_player'), game_tx_bits_per_s=game_traffic.get('tx_bits_per_s'), bot_tx_bytes=bot_traffic.get('tx_bytes')), run_span_traffic=dict(game_tx_bytes=value['run_span_traffic']['game']['tx_bytes'], bot_tx_bytes=value['run_span_traffic']['bot']['tx_bytes']))


def _compact_economics(economy):
    session = economy['session_estimate']
    return dict(nominal_game_tier={key: economy['nominal_game_tier'][key] for key in ('monthly_usd', 'display', 'confirmed_players', 'players_per_monthly_game_usd', 'is_lower_bound', 'meaning')}, session_estimate=dict(label=session['label'], lifetime_s=session['lifetime_s'], total_estimated_usd=session['total_estimated_usd'], hosts={role: {key: session['hosts'][role][key] for key in ('size_slug', 'compute_usd', 'measured_outbound_bytes_lower_bound', 'transfer_overage_usd')} for role in ROLES}),
                admission_estimate={key: economy['admission_estimate'][key] for key in ('label', 'session_estimate_usd', 'max_estimated_session_usd')}, management_host=dict(economy['management_host']), invoices=dict(statement=economy['invoices']['statement'], recorded=[{key: item.get(key) for key in ('period', 'amount_usd', 'recorded_at')} for item in economy['invoices']['recorded']]))


def _gate_policy():
    """The limit each gate was held to, from the scorer's own policy so that published text cannot drift from what decided."""
    policy = capacity_scorer.POLICY
    return dict(policy_sha256=capacity_scorer.POLICY_SHA256, tick_budget=dict(budget_ns=policy['tick_budget_ns'], over_percent_strictly_below=policy['tick_over_percent_strictly_below']), rtt_p95=dict(limit_ms_strictly_below=policy['rtt_limit_ms_strictly_below'], quantile_percent=policy['rtt_quantile']['percent']), enet_loss=dict(limit_strictly_below=policy['enet_loss']['limit_strictly_below']),
                game_socket_drops=dict(allowed=0), continuity=dict(unexpected_disconnects_allowed=0), bot_errors=dict(total_allowed=0))


def compact(document, sums_sha256, raw_files, raw_bytes):
    """The compact per-session summary. Built from named fields only: a field no one named here, on any socket or collector, cannot reach it. Free text from a host stays private, and reason codes stand in for it."""
    results = document['results']
    measurement, evidence, cleanup = results['measurement'], results['evidence'], results['cleanup']
    claim = measurement['claim']
    condition = document['condition']
    return dict(schema=COMPACT_SCHEMA, provider=document['provider'], label=document['label'], session_id=document['session_id'], separate_from_cax11=document['separate_from_cax11'], establishes=document['establishes'], as_of=document['as_of'],
                results=dict(measurement=dict(search_status=measurement['search_status'], claim={key: claim.get(key) for key in ('kind', 'players', 'lower_bound', 'search_cap_reached', 'confirmed', 'statement')}, history_not_vouched_for=_safe_text((measurement['journal_claim_withheld'] or {}).get('statement'))), evidence=dict(status=evidence['status'], files=evidence['files'], bytes=evidence['bytes'], partial_files=evidence['partial_files'], corrupt_files=evidence['corrupt_files'], required_session_missing=len(evidence['required_session_missing']), controller_inputs_missing=len(evidence['controller_inputs_missing']), controller_inputs_corrupt=len(evidence['controller_inputs_corrupt']), paths_not_inventoried=len(evidence['not_inventoried'])),
                             cleanup=dict(known=cleanup['known'], outcome=cleanup['outcome'], overall=cleanup.get('overall'), verified_absent=cleanup['verified_absent'], verified_at=cleanup.get('verified_at'), overrun_s=cleanup.get('overrun_s'), overdue=cleanup.get('overdue'), unresolved_creates=cleanup.get('unresolved_creates'), statement=cleanup['statement'], resources=[dict(kind=item['kind'], status=item['status'], attempts=item['attempts'], verified_absent_at=item['verified_absent_at']) for item in cleanup.get('resources') or ()], incidents=[dict(kind=item['kind'], status=item['status'], opened_at=item['opened_at'], resolved_at=item['resolved_at'], overrun_s=item['overrun_s']) for item in cleanup.get('incidents') or ()])),
                condition=dict(region=condition['region'], public_route=condition['public_route'], game=condition['game'], bot=condition['bot'], workload=condition['workload'], telemetry_schema=condition['telemetry_schema']), source={key: document['source'].get(key) for key in ('benchmark_sha', 'controller_sha', 'adapter_sha', 'rust_toolchain', 'target_triple', 'profile', 'cargo_lock_sha256', 'server_config_sha256', 'binary_sha256')}, manifest_sha256=document['manifest_sha256'], runs=[_compact_run(row) for row in document['runs']], confirmations=document['confirmations'], economics=_compact_economics(document['economics']),
                gate_policy=_gate_policy(), raw_evidence=dict(policy=RAW_EVIDENCE_POLICY, inventory_file='SHA256SUMS', inventory_sha256=sums_sha256, files=raw_files, bytes=raw_bytes), reads_as=READS_AS_DIAGNOSTIC)


def render_compact(summary):
    results = summary['results']
    measurement, evidence, cleanup = results['measurement'], results['evidence'], results['cleanup']
    game, bot = summary['condition']['game'], summary['condition']['bot']
    lines = ['# %s test session `%s`' % (summary['provider'], summary['session_id']), '', '**%s**' % measurement['claim']['statement'], '', summary['separate_from_cax11'], '', 'Condition `%s`. Game `%s` (%s vCPU, %s MiB) and bot `%s` (%s vCPU, %s MiB) in `%s`, over `%s`.' % (summary['label'], _cell(game['size_slug']), _cell(game['vcpus']), _cell(game['memory_mib']), _cell(bot['size_slug']), _cell(bot['vcpus']), _cell(bot['memory_mib']), _cell(summary['condition']['region']), _cell(summary['condition']['public_route'])), 'Source `%s`, controller `%s`, adapter `%s`.' % (_cell(summary['source']['benchmark_sha']), _cell(summary['source']['controller_sha']), _cell(summary['source']['adapter_sha'])), '',
             '| Result | Status |', '| --- | --- |', '| Measurement | `%s` |' % _cell(measurement['search_status']), '| Evidence | `%s` (%s files, %s bytes) |' % (_cell(evidence['status']), _cell(evidence['files']), _cell(evidence['bytes'])), '| Cleanup | `%s` |' % _cell(cleanup['overall'] or cleanup['outcome']), '', cleanup['statement'], '']
    if measurement['history_not_vouched_for']:
        lines += ['History, not vouched for: ' + measurement['history_not_vouched_for'], '']
    gaps = [(evidence['required_session_missing'], 'session record(s) missing'), (evidence['controller_inputs_missing'], 'required controller or provisioning input(s) missing'), (evidence['controller_inputs_corrupt'], 'required controller or provisioning input(s) not the recorded bytes'), (evidence['paths_not_inventoried'], 'path(s) could not be listed or read, so `SHA256SUMS` cannot be said to cover every raw file')]
    lines += ['- Evidence gap: %d %s.' % gap for gap in gaps if gap[0]]
    lines += [''] if any(gap[0] for gap in gaps) else []
    lines += ['| # | Phase | Target | Rep | Hold (s) | Outcome | Offered load | Verified | Tick p95 (ns) | RTT p95 (ms) | Loss est. per-second mean peak | Loss est. peer peak (bot) | Game CPU %core | Game tx B/s/player |', '| ---: | --- | ---: | ---: | ---: | --- | --- | --- | ---: | ---: | ---: | --- | ---: | ---: |']
    for row in summary['runs']:
        lines.append('| %d | %s | %d | %d | %d | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (row['ordinal'], row['phase'], row['target'], row['repetition'], row['hold_s'], row['outcome'] or 'pending', row['offered_load'] or 'no score', 'yes' if row['verified'] else 'no', _cell(row['ticks']['p95_work_ns']), _cell(row['peers']['rtt_p95_ms']), _cell(row['peers']['loss_estimate_peak_per_second_mean']), _peer_peak_cell(row['peers']), _cell(row['game_cpu_percent_of_one_core']), _cell(row['window_traffic']['game_tx_bytes_per_s_per_player'])))
    economy = summary['economics']
    limits = summary['gate_policy']
    lines += ['', '**Gates.** Fewer than %s%% of Ticks above %s ns, pooled RTT p%s strictly below %s ms, ENet loss estimate per-second mean strictly below %s, and zero game socket drops, unexpected disconnects and bot errors.' % (limits['tick_budget']['over_percent_strictly_below'], limits['tick_budget']['budget_ns'], limits['rtt_p95']['quantile_percent'], limits['rtt_p95']['limit_ms_strictly_below'], limits['enet_loss']['limit_strictly_below'])]
    lines += ['', '**Cost.** Nominal game tier $%s/month, %s confirmed players per monthly game-host dollar. Both-host session estimate, not an invoice: %s USD over %s s. Admission reserved %s USD. Management host $%s/month, disclosed separately and in none of these. %s' % (_cell(economy['nominal_game_tier']['monthly_usd']), _cell(economy['nominal_game_tier']['players_per_monthly_game_usd']), _cell(economy['session_estimate']['total_estimated_usd']), _cell(economy['session_estimate']['lifetime_s']), _cell(economy['admission_estimate']['session_estimate_usd']), _cell(economy['management_host']['monthly_usd']), economy['invoices']['statement']), '',
              '**Raw evidence.** ' + summary['raw_evidence']['policy'] + ' Inventory: `SHA256SUMS` (sha256 `%s`, %s files, %s bytes).' % (_cell(summary['raw_evidence']['inventory_sha256']), _cell(summary['raw_evidence']['files']), _cell(summary['raw_evidence']['bytes'])), '', summary['reads_as'], '']
    return '\n'.join(lines)


def canonical(document):
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + '\n'


def scrub(value, sensitive=()):
    """For the private report. Recognized credentials and this session's addresses go, whatever field holds them. A credential pattern that survives this is a defect, and the caller refuses to write."""
    if isinstance(value, dict):
        return {key: scrub(child, sensitive) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(child, sensitive) for child in value]
    if isinstance(value, str):
        for pattern in manifest_mod.SECRET_PATTERNS:
            value = pattern.sub('[REDACTED]', value)
        for item in sensitive:
            value = value.replace(item, '[REDACTED]')
    return value
