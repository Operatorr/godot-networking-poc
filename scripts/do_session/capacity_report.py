#!/usr/bin/env python3
"""A reproducible report of one run's score and one session's search. Pure over retained files, with nothing live and no clock.

    capacity_report.py --session-dir D [--out DIR]

A report renders what the scorer and the search decided, and adds no judgement of its own: rendering one proves nothing, and a run the scorer did not pass reads as what it is.
The same files give the same bytes, which ``test_capacity_scorer`` checks. Compact findings and the raw evidence's inventory are slice 7's.
"""
import argparse
import hashlib
import json
import pathlib
import sys

import do_session
import search

SCORE_FILE = 'score.json'
RUN_REPORT_FILE = 'score-report.md'
SEARCH_REPORT_SCHEMA = 'omega.do-session.capacity-report/1'
GATE_LABELS = dict(continuity='N/N authenticated throughout', bot_errors='Zero bot errors', tick_budget='Strictly under 1% of Ticks above 33.3 ms', game_socket_drops='Zero game-socket drops',
                   rtt_p95='Pooled RTT p95 strictly below 150 ms (ENet smoothed RTT)', enet_loss='Per-second mean ENet loss estimate strictly below 2%')


def _ratio(value):
    return 'unknown' if not value else '%s (%.6f)' % (value['exact'], value['approximate'])


def gate_value(name, gate):
    """The numbers behind a gate, with nothing rounded away from the comparison."""
    if name == 'tick_budget':
        if 'ticks_wide' in gate and 'worst_possible_ratio' in gate:
            return 'over/ticks at most %s, at least %s' % (_ratio(gate.get('worst_possible_ratio')), _ratio(gate.get('least_possible_ratio')))
        if 'ticks' in gate:
            return 'ramp: %s over/ticks %s' % (gate.get('over'), _ratio(gate.get('ratio')))
    if name == 'rtt_p95' and 'p95_ms' in gate:
        return '%s ms at rank %d of %d samples, max %s ms' % (gate['p95_ms'], gate['rank'], gate['samples'], gate['max_ms'])
    if name == 'enet_loss' and 'per_second_mean_peak' in gate:
        peak = gate['per_second_mean_peak']
        return 'peak %s at second %d; window mean %s; %d of %d seconds evaluated, %d readings borrowed' % (_ratio(peak['ratio']), peak['second'], _ratio(gate.get('window_mean_of_seconds')), gate['seconds_evaluated'], gate['seconds'], gate['borrowed_readings'])
    if name == 'game_socket_drops' and 'drops_in_widest_interval' in gate:
        return '%d in the widest interval, %s proven inside' % (gate['drops_in_widest_interval'], gate.get('drops_proven_inside', 0))
    if name == 'continuity':
        return '%s unexpected disconnects' % gate.get('unexpected_disconnects_in_window', 'unknown')
    if name == 'bot_errors' and 'errors' in gate:
        return '%d errors, %d of them the disconnect itself; %d independent' % (gate['errors'], gate['errors_that_are_the_disconnect_itself'], gate['independent'])
    return gate.get('why', '')


def render_run(score):
    """The run's own record of its decision. ``capacity_scorer`` retains it beside ``score.json``."""
    trial = score['trial']
    lines = ['# Run score: %s' % score['run_id'], '',
             '**%s** (`%s`). %s target %s, hold %s s, repetition %s. A single run establishes no capacity.' % (score['classification'], score['outcome'], trial.get('phase'), trial.get('target'), trial.get('hold_s'), trial.get('repetition')), '']
    lines += ['- ' + reason for reason in score['reasons']]
    lines += ['', '| Gate | Verdict | Value |', '| --- | --- | --- |']
    for name in GATE_LABELS:
        gate = score['gates'][name]
        lines.append('| %s | %s | %s |' % (GATE_LABELS[name], gate['verdict'], gate_value(name, gate).replace('|', '/')))
    validity = score['validity']
    offered = score.get('offered_load') or {}
    lines += ['', '**Offered load:** %s. Input %s, generator sockets %s.' % (validity['verdict'], validity['offered_input'], validity['generator_sockets'])]
    if offered.get('bots'):
        lines.append('Sent %s of %s scheduled frames; worst bot %s at %s.' % (offered['sent_total'], offered['scheduled_total'], offered['worst_bot'], _ratio(offered['worst_ratio'])))
    for item in validity.get('independent_failures') or ():
        lines.append('- Independent generator failure: %s %s' % (item.get('code'), item.get('detail', '')))
    for item in validity.get('unproven') or ():
        lines.append('- Not proven: %s' % item)
    departures = score['attribution'].get('departures') or []
    if departures:
        lines += ['', '**Lost in the window** (`observation_lag_ns` is the bot seeing it minus the server\'s event):', '', '| Bot | Cause on record | Bot reason | Server reason | Order | Lag (ns) |', '| ---: | --- | ---: | ---: | --- | --- |']
        for item in departures[:40]:
            lines.append('| %s | %s | %s | %s | %s | %s |' % (item['bot'], item['cause'], item['reason'], item['server_reason'], item['order'], item['observation_lag_ns']))
    exit_facts = score['attribution'].get('game_exit') or {}
    if exit_facts.get('lost'):
        lines += ['', '**Game process:** ended before the swarm: %s, exit %s, signal %s.' % (exit_facts.get('kind'), exit_facts.get('returncode'), exit_facts.get('signal'))]
    inputs = score['inputs']
    lines += ['', 'Scorer `%s`, policy `%s`, measurement schema `%s` `%s`, proof `%s` over `%s`, execution `%s`.' % (score['scorer'], score['policy_sha256'], inputs.get('measurement_schema'), inputs.get('measurement_schema_sha256'), inputs.get('proof_status'), inputs.get('window_proof_sha256'), inputs.get('execution_sha256')),
              'ENet loss is a smoothed estimate of reliable commands lost, not a measured fraction of datagrams dropped. CPU, memory, bandwidth and gaps are diagnostics and decide nothing. The whole-run `report.json` decides nothing.', '']
    return '\n'.join(lines)


def _state(session_dir):
    """The search as the planner journal recorded it, with the manifest's hash verified first.

    A selection that was never dispatched left its run untouched, so it is no trial of this search. A run whose classification is retained has its verdict there: that file is written before the
    registry commit, and a returning controller only ever commits that verdict, so a journal mirror that a crash left behind must not make a terminal fact look pending.
    """
    _, _, state, _ = do_session.load_session(session_dir)
    kept = []
    for record in state.records:
        run_dir = session_dir / 'runs' / record.trial.run_id
        if record.outcome is None:
            verdict = _retained_verdict(run_dir / 'classification.json')
            if verdict is not None:
                record = search.TrialRecord(record.trial, verdict, 'runs/%s/classification.json#sha256:%s' % (record.trial.run_id, _file_sha256(run_dir / 'classification.json')))
            elif not (run_dir / 'grant.json').exists():
                continue
        kept.append(record)
    return search.SearchState(state.condition_id, kept, state.stop_reason)


def _retained_verdict(path):
    try:
        outcome = json.loads(path.read_text())['verdict']['outcome']
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return outcome if outcome in search.OUTCOMES else None


def _file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def build(session_dir):
    """One document for one session. Every trial stays in it, whatever happened to it, with hashes of the files its row came from."""
    session_dir = pathlib.Path(session_dir)
    state = _state(session_dir)
    derived, claim = search.derive(state), search.capacity_claim(state)
    trials = []
    for record in state.records:
        trial = record.trial
        run_dir = session_dir / 'runs' / trial.run_id
        row = dict(run_id=trial.run_id, ordinal=trial.ordinal, phase=trial.phase, target=trial.target, repetition=trial.repetition, hold_s=trial.hold_s, predecessors=list(trial.predecessors), outcome=record.outcome, evidence_ref=record.evidence_ref,
                   score_sha256=_file_sha256(run_dir / SCORE_FILE), classification_sha256=_file_sha256(run_dir / 'classification.json'), window_proof_sha256=_file_sha256(run_dir / 'window-proof.json'))
        path = run_dir / SCORE_FILE
        if path.exists():
            try:
                score = json.loads(path.read_text())
                row.update(classification=score.get('classification'), reasons=score.get('reasons'), gates={name: gate.get('verdict') for name, gate in (score.get('gates') or {}).items()}, offered_load=(score.get('validity') or {}).get('verdict'), values={name: gate_value(name, gate) for name, gate in (score.get('gates') or {}).items()})
            except ValueError:
                row.update(classification=None, reasons=['score.json no longer parses'])
        else:
            row.update(classification=None, reasons=[], gates={}, offered_load=None, values={})
        trials.append(row)
    return dict(schema=SEARCH_REPORT_SCHEMA, session_id=state.condition_id, status=derived['status'], detail=derived['detail'], claim=claim, observations=search.observations(state), counts=derived['counts'], trials=trials, establishes=claim['confirmed'])


def render_search(report):
    claim = report['claim']
    lines = ['# Capacity search: %s' % report['session_id'], '', '**%s**' % claim['statement'], '', 'Status `%s`. %s' % (report['status'], report['detail']), '',
             '| # | Phase | Target | Rep | Hold (s) | Outcome | Offered load | Continuity | Errors | Ticks | Game socket | RTT p95 | ENet loss |', '| ---: | --- | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- | --- | --- |']
    for row in report['trials']:
        gates = row.get('gates') or {}
        cell = lambda name: gates.get(name, 'no score')
        lines.append('| %d | %s | %d | %d | %d | %s | %s | %s | %s | %s | %s | %s | %s |' % (row['ordinal'], row['phase'], row['target'], row['repetition'], row['hold_s'], row['outcome'] or 'pending', row.get('offered_load') or 'no score',
                                                                                       cell('continuity'), cell('bot_errors'), cell('tick_budget'), cell('game_socket_drops'), cell('rtt_p95'), cell('enet_loss')))
    for row in report['trials']:
        lines += ['', '**%s**: %s' % (row['run_id'], row['outcome'] or 'pending')]
        lines += ['- ' + str(reason) for reason in (row.get('reasons') or ())]
        lines += ['- %s: %s' % (name, value) for name, value in sorted((row.get('values') or {}).items()) if value]
    lines += ['', 'CPU, memory, bandwidth and variance are diagnostics and add no gate. ENet loss is a smoothed estimate, not a measured fraction of datagrams dropped. This report renders retained decisions and proves nothing by existing.', '']
    return '\n'.join(lines)


def canonical(report):
    return json.dumps(report, indent=2, sort_keys=True) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--session-dir', required=True)
    parser.add_argument('--out', help='a directory for capacity-report.json and capacity-report.md, which must not exist yet. Without it the Markdown goes to stdout')
    args = parser.parse_args(argv)
    report = build(args.session_dir)
    if args.out:
        out = pathlib.Path(args.out)
        out.mkdir(parents=True)
        (out / 'capacity-report.json').write_text(canonical(report))
        (out / 'capacity-report.md').write_text(render_search(report))
    else:
        sys.stdout.write(render_search(report))
    return 0


if __name__ == '__main__':
    sys.exit(main())
