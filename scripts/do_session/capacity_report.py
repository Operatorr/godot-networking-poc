#!/usr/bin/env python3
"""A reproducible report of one run's score and one session's search. Pure over retained files, with nothing live and no clock.

    capacity_report.py --session-dir D [--out DIR]

A report renders what the scorer and the search decided, and adds no judgement of its own: rendering one proves nothing, and a run the scorer did not pass reads as what it is.
It does check what it renders. Each trial's journal outcome is followed through the classification and score it names, by the hashes recorded when they were written, to the run's own proof and
execution record. Where those disagree or cannot be verified, the report says so and claims nothing, and keeps the journal's claim apart as history.
The same files give the same bytes, which ``test_capacity_scorer`` checks. Compact findings and the raw evidence's inventory are slice 7's.
"""
import argparse
import hashlib
import json
import pathlib
import sys

import capacity_scorer
import do_session
import search

SCORE_FILE = capacity_scorer.SCORE_FILE
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


def _state(session_dir, manifest, sha, state):
    """The search as the planner journal recorded it. A selection that was never dispatched left its run untouched, so it is no trial of this search.

    A run whose classification is retained has its verdict there, when that file holds up: it is written before the registry commit, and a returning controller only ever commits
    that verdict, so a journal mirror that a crash left behind must not make a terminal fact look pending.
    """
    kept = []
    for record in state.records:
        run_dir = session_dir / 'runs' / record.trial.run_id
        if record.outcome is None:
            verdict = _retained_verdict(run_dir / 'classification.json', _expectation(run_dir, record, manifest, sha))
            if verdict is not None:
                record = search.TrialRecord(record.trial, verdict, 'runs/%s/classification.json#sha256:%s' % (record.trial.run_id, _file_sha256(run_dir / 'classification.json')))
            elif not (run_dir / 'grant.json').exists():
                continue
        kept.append(record)
    return search.SearchState(state.condition_id, kept, state.stop_reason)


def _expectation(run_dir, record, manifest, sha):
    return capacity_scorer.retained_expectation(run_dir, record.trial.to_dict(), manifest['session']['id'], sha, (manifest.get('source') or {}).get('controller_sha'))


def _read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _retained_verdict(path, expected):
    document = _read(path)
    if document is None or capacity_scorer.classification_problems(document, expected):
        return None
    return document['verdict']['outcome']


def _file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def audit(session_dir, manifest, sha, record):
    """What the retained files say of one trial, set against what the journal says. A file's current hash is only ever compared with a hash recorded earlier, and never taken as the expected one.

    Returns (problems, verdict, score): the verdict and score only when they hold up, so nothing unverified can be rendered as this run's. A stop fact on record beside an outcome that does not stop is a problem of its own: the
    outcome may be immutable and intact, and it still cannot be vouched for.
    """
    run_id = record.trial.run_id
    run_dir = session_dir / 'runs' / run_id
    expected = _expectation(run_dir, record, manifest, sha)
    problems = []
    facts, unverified = capacity_scorer.stop_records(run_dir, expected)
    if record.outcome is not None and record.outcome not in search.STOPPING:
        problems += ['the journal says %s, and %s records a stop fact: %s' % (record.outcome, fact['record'], '; '.join(str(item) for item in fact['details'])) for fact in facts]
    problems += ['%s says a run stopped, and cannot be held to this run: %s' % (item['record'], '; '.join(item['problems'])) for item in unverified]
    reference = capacity_scorer.parse_reference(record.evidence_ref)
    verdict = None
    if record.outcome is not None:
        name = reference[1] if reference else 'classification.json'
        if record.evidence_ref is not None and (reference is None or reference[0] != run_id):
            problems.append('the journal names evidence that is no retained file of this run: %s' % record.evidence_ref)
        elif not (run_dir / name).exists():
            problems.append('the journal says %s and %s is missing' % (record.outcome, name))
        elif reference is not None and _file_sha256(run_dir / name) != reference[2]:
            problems.append('%s is no longer the file the journal recorded' % name)
        else:
            document = _read(run_dir / name)
            found = capacity_scorer.classification_problems(document, expected)
            problems += ['%s: %s' % (name, item) for item in found]
            if not found:
                verdict = document['verdict']
                if verdict['outcome'] != record.outcome:
                    problems.append('the journal says %s and %s says %s' % (record.outcome, name, verdict['outcome']))
                    verdict = None
    if (run_dir / 'classification.json').exists() and (reference is None or reference[1] != 'classification.json'):
        found = capacity_scorer.classification_problems(_read(run_dir / 'classification.json'), expected)
        problems += ['classification.json: ' + item for item in found]
    score = None
    if (run_dir / SCORE_FILE).exists():
        score, found = capacity_scorer.bound_score(run_dir / SCORE_FILE, expected)
        if found:
            problems += ['%s: %s' % (SCORE_FILE, item) for item in found]
            score = None
    return sorted(set(problems)), verdict, score


def build(session_dir):
    """One document for one session. Every trial stays in it, whatever happened to it, with hashes of the files its row came from."""
    session_dir = pathlib.Path(session_dir)
    manifest, sha, journal, _ = do_session.load_session(session_dir)
    state = _state(session_dir, manifest, sha, journal)
    derived, journal_claim = search.derive(state), search.capacity_claim(state)
    trials = []
    for record in state.records:
        trial = record.trial
        run_dir = session_dir / 'runs' / trial.run_id
        problems, verdict, score = audit(session_dir, manifest, sha, record)
        facts, unverified = capacity_scorer.stop_records(run_dir, _expectation(run_dir, record, manifest, sha))
        row = dict(run_id=trial.run_id, ordinal=trial.ordinal, phase=trial.phase, target=trial.target, repetition=trial.repetition, hold_s=trial.hold_s, predecessors=list(trial.predecessors), outcome=record.outcome, evidence_ref=record.evidence_ref, evidence_problems=problems,
                   hard_facts=facts, unverified_stop_records=unverified, superseded_decisions=list((verdict or {}).get('supersedes') or ()),
                   score_sha256=_file_sha256(run_dir / SCORE_FILE), classification_sha256=_file_sha256(run_dir / 'classification.json'), window_proof_sha256=_file_sha256(run_dir / 'window-proof.json'))
        if score is not None:
            row.update(classification=score.get('classification'), reasons=score.get('reasons'), gates={name: gate.get('verdict') for name, gate in (score.get('gates') or {}).items()}, offered_load=(score.get('validity') or {}).get('verdict'), values={name: gate_value(name, gate) for name, gate in (score.get('gates') or {}).items()})
            if verdict is not None and verdict.get('outcome') != score.get('outcome'):
                row['reasons'] = list(verdict.get('reasons') or ()) + list(score.get('reasons') or ())
            if row['superseded_decisions']:
                row['classification'] = None    # the gates and offered load stay readable, under a row that says they are history
        else:
            row.update(classification=None, reasons=list((verdict or {}).get('reasons') or ()), gates={}, offered_load=None, values={})
        trials.append(row)
    disputed = [row['run_id'] for row in trials if row['evidence_problems']]
    claim = journal_claim
    if disputed:
        claim = dict(kind='evidence_disagreement', players=None, lower_bound=None, search_cap_reached=False, confirmed=False,
                     statement='No evidence-backed claim: the retained files of %d of %d trials disagree with the journal or cannot be verified. What the journal says is kept apart as history, and is not verified here.' % (len(disputed), len(trials)))
    superseded = [row['run_id'] for row in trials if row['superseded_decisions']]
    evidence = dict(verified=not disputed and not superseded, disputed_trials=disputed, superseded_trials=superseded, trials_with_stop_facts=[row['run_id'] for row in trials if row['hard_facts']], trials_with_unverified_stop_records=[row['run_id'] for row in trials if row['unverified_stop_records']])
    return dict(schema=SEARCH_REPORT_SCHEMA, session_id=state.condition_id, status=derived['status'], detail=derived['detail'], claim=claim, journal_claim=journal_claim, evidence=evidence, observations=search.observations(state), counts=derived['counts'], trials=trials, establishes=claim['confirmed'])


def render_search(report):
    claim = report['claim']
    lines = ['# Capacity search: %s' % report['session_id'], '', '**%s**' % claim['statement'], '']
    if report['evidence']['disputed_trials']:
        lines += ['**History only, from the journal and not verified:** %s' % report['journal_claim']['statement'], '']
    if report['evidence']['superseded_trials']:
        lines += ['**Not verified as a whole.** A stop fact outranked a retained decision in: %s. Those decisions are kept as history and do not stand.' % ', '.join(report['evidence']['superseded_trials']), '']
    lines += ['Status `%s`. %s' % (report['status'], report['detail']), '',
             '| # | Phase | Target | Rep | Hold (s) | Outcome | Offered load | Continuity | Errors | Ticks | Game socket | RTT p95 | ENet loss |', '| ---: | --- | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- | --- | --- |']
    for row in report['trials']:
        gates = row.get('gates') or {}
        cell = lambda name: gates.get(name, 'no score')
        lines.append('| %d | %s | %d | %d | %d | %s | %s | %s | %s | %s | %s | %s | %s |' % (row['ordinal'], row['phase'], row['target'], row['repetition'], row['hold_s'], row['outcome'] or 'pending', row.get('offered_load') or 'no score',
                                                                                       cell('continuity'), cell('bot_errors'), cell('tick_budget'), cell('game_socket_drops'), cell('rtt_p95'), cell('enet_loss')))
    for row in report['trials']:
        lines += ['', '**%s**: %s' % (row['run_id'], row['outcome'] or 'pending')]
        lines += ['- Not verified: ' + problem for problem in row['evidence_problems']]
        lines += ['- Stop fact %s (%s): %s' % (fact['outcome'], fact['record'], '; '.join(str(item) for item in fact['details'])) for fact in row.get('hard_facts') or ()]
        lines += ['- Unverified stop record %s (sha256 %s), not this session\'s fact: %s' % (item['record'], item['sha256'], '; '.join(item['problems'])) for item in row.get('unverified_stop_records') or ()]
        lines += ['- History, does not stand: %s said %s (sha256 %s). The gates below are what it decided.' % (item['file'], item['outcome'], item['sha256']) for item in row.get('superseded_decisions') or ()]
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
