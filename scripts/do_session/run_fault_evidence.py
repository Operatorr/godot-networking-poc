#!/usr/bin/env python3
"""Regenerate the retained offline run timelines for handoff slice 4 (issue #67).

Each scenario runs the real executor, registry and watchdog against a fake remote on a scripted clock. The output is compact and
byte-reproducible, holds no credential and proves nothing about a live account or a measurement: the outcomes are scripted by the
fixture, because no scorer exists yet. ``test_run_fault_evidence`` regenerates it and compares it with the committed SHA256SUMS.

    python3 run_fault_evidence.py --out ../../docs/netcode/perf-notes/digitalocean-capacity/offline-faults/slice4
"""
import argparse
import hashlib
import json
import pathlib
import sys

import fault_evidence
import guest_agent
import manifest as manifest_mod
import registry
import run_executor
import run_fixtures as rf
import run_plan
import search
import session_clock

TRACE_EVENTS = ('run_dispatch_intent', 'run_progress', 'run_interrupted', 'run_outcome', 'batch_stopped', 'resumed', 'control_acquired', 'cleanup_intent')
SCORE = {25: search.PASS, 50: search.FAIL, 30: search.FAIL}


def scorer(outcomes=None, default=search.PASS):
    return rf.scripted_scorer(SCORE if outcomes is None else outcomes, default)


def crash(sim, point, score=None):
    executor = sim.executor(scorer=score or scorer(), failpoint=rf.crash_at(point))
    try:
        executor.execute()
    except rf.SimulatedCrash:
        return
    raise AssertionError(point + ' was not reached')


def crash_between_runs(sim):
    executor = sim.executor(scorer=scorer())
    hits = [0]

    def second_selection(name):
        if name == 'after_selection':
            hits[0] += 1
            if hits[0] == 2:
                raise rf.SimulatedCrash(name)
    executor.failpoint = second_selection
    try:
        executor.execute()
    except rf.SimulatedCrash:
        return
    raise AssertionError('the second selection was not reached')


def resume(sim, score=None, **options):
    executor, control = sim.controller(scorer=score or scorer(), **options)
    return executor, executor.resume('operator: resume remaining runs', control)


def outcomes(sim):
    return [r['outcome'] for r in sim.records()]


def starts(sim, role='game'):
    return len(sim.guests.runner_steps(role, 'start'))


# ---- fresh runs and classification ----------------------------------------------------------------

def fresh_runs_reach_a_confirmed_observation(sim, checks):
    result = sim.executor(scorer=scorer()).execute()
    checks('the frozen search finished', (result.status, result.search_status) == (run_executor.FINISHED, 'confirmed'))
    checks('one fresh start per run on each host', starts(sim, 'game') == starts(sim, 'bot') == len(sim.records()))
    ledger = sim.guests.hosts['game'].ledger
    pids = [e['processes']['game']['pid'] for e in ledger if 'processes' in e]
    inodes = [e['socket_inodes'][0] for e in ledger if e.get('sealed')]
    checks('no process or socket identity repeats', len(pids) == len(set(pids)) and len(inodes) == len(set(inodes)))
    checks('the pair was never replaced', len(sim.creates('/v2/droplets')) == 2)


def capacity_failure_advances_only_the_search(sim, checks):
    sim.guests.game_crash_after_s = 20.0
    result = sim.executor(scorer=scorer({25: search.FAIL, 5: search.FAIL})).execute()
    checks('a scorer attributed both failures to the game host', outcomes(sim) == [search.FAIL, search.FAIL])
    checks('the search reached its own end', result.search_status == 'no_passing_target')
    checks('the batch has no terminal failure', sim.status_now()['terminal_failure'] is None)


def generator_crash_is_invalid_load(sim, checks):
    sim.guests.bot_exit = (77, None)
    score = scorer({25: search.FAIL})
    result = sim.executor(scorer=score).execute()
    checks('recorded as invalid load', outcomes(sim) == [search.INVALID_LOAD])
    checks('no scorer was consulted', score.seen == [])
    checks('remaining runs stopped', result.search_status == 'stopped_invalid_load' and len(sim.records()) == 1)


def lost_host_is_a_terminal_infrastructure_failure(sim, checks):
    sim.guests.bot_seconds = 500.0
    sim.guests.unreachable.add(('bot', 'status'))
    result = sim.executor(scorer=scorer()).execute()
    checks('recorded as infrastructure', outcomes(sim) == [search.INFRASTRUCTURE_FAILURE])
    checks('remaining runs stopped', result.search_status == 'stopped_infrastructure_failure')


def no_scorer_establishes_nothing(sim, checks):
    result = sim.executor().execute()
    checks('a finished run with no scorer is inconclusive', outcomes(sim) == [search.INCONCLUSIVE])
    checks('and the batch stops', result.search_status == 'stopped_inconclusive_evidence')


def hung_workload_is_stopped_by_its_bound(sim, checks):
    sim.guests.bot_hangs = True
    score = scorer({25: search.FAIL})
    sim.executor(scorer=score).execute()
    row = sim.records()[0]
    checks('never called capacity', row['outcome'] == search.INCONCLUSIVE and score.seen == [])
    checks('the guest stopped it by itself', sim.guests.hosts['bot'].runs[row['run_id']].stop_reason == 'bound_exhausted')
    checks('finished inside the grant', session_clock.parse(row['finished_at']) <= session_clock.parse(row['must_stop_by']) + 1)


# ---- crash windows --------------------------------------------------------------------------------

def crash_before_dispatch_keeps_the_trial_untouched(sim, checks):
    crash(sim, 'before_dispatch_commit')
    checks('nothing was dispatched', sim.records() == [])
    executor, outcome = resume(sim)
    checks('explicit resume names the same trial', outcome['resumed'] and outcome['next_run_id'].endswith('t01-coarse-n025-r1'))
    executor.execute()
    checks('it ran exactly once', starts(sim) == len(sim.records()))


def crash_after_dispatch_stops_the_dependent_path(sim, checks):
    crash(sim, 'after_dispatch_commit')
    _, outcome = resume(sim)
    checks('the first rung is incomplete, not replayed', outcomes(sim) == [search.INCOMPLETE] and starts(sim) == 0)
    checks('resume refuses because nothing further can be decided', outcome['code'] == 'no_eligible_untouched_work')


def crash_during_active_run_preserves_it(sim, checks):
    crash(sim, 'after_running_commit')
    run_id = sim.records()[0]['run_id']
    _, outcome = resume(sim)
    checks('classified incomplete', outcomes(sim) == [search.INCOMPLETE])
    checks('resume is refused', outcome['code'] == 'no_eligible_untouched_work')
    checks('the same processes were stopped, not restarted', starts(sim, 'game') == 1 and starts(sim, 'bot') == 1)
    sealed = [sim.guests.hosts[role].runs[run_id].sealed for role in ('game', 'bot')]
    checks('both directories are sealed as interrupted', all(s['interrupted'] == 'controller_replaced' for s in sealed))


def crash_before_outcome_keeps_the_verdict(sim, checks):
    crash(sim, 'before_outcome_commit')
    checks('no outcome reached the registry', outcomes(sim) == [None])
    second_opinion = scorer({25: search.FAIL})
    _, outcome = resume(sim, score=second_opinion)
    checks('the verdict already reached is recorded', outcomes(sim) == [search.PASS])
    checks('it was not scored again', second_opinion.seen == [])
    checks('work after it is eligible', outcome['resumed'])


def crash_before_a_terminal_outcome_cannot_escape_it(sim, checks):
    sim.guests.bot_exit = (77, None)
    crash(sim, 'before_outcome_commit')
    _, outcome = resume(sim)
    checks('the terminal verdict is recorded', outcomes(sim) == [search.INVALID_LOAD])
    checks('resume is refused', outcome['code'] == 'terminal_failure')


def crash_after_outcome_repairs_only_the_mirror(sim, checks):
    crash(sim, 'after_outcome_commit')
    executor, outcome = resume(sim)
    checks('resume continues', outcome['resumed'])
    executor.execute()
    entries = [json.loads(line) for line in (sim.stack.root / 'search_journal.ndjson').read_text().splitlines()]
    mirrored = [e['run_id'] for e in entries if e['kind'] == 'outcome']
    checks('each outcome is mirrored once', len(mirrored) == len(set(mirrored)) == len(sim.records()))


def incomplete_confirmation_leaves_siblings_eligible(sim, checks):
    executor = sim.executor(scorer=scorer())
    hits = [0]

    def in_confirmation(name):
        if name == 'after_running_commit':
            hits[0] += 1
            if hits[0] == 4:
                raise rf.SimulatedCrash(name)
    executor.failpoint = in_confirmation
    try:
        executor.execute()
    except rf.SimulatedCrash:
        pass
    resumed, outcome = resume(sim)
    checks('the next sibling is eligible', outcome['resumed'] and '-confirm-n025-r2' in outcome['next_run_id'])
    result = resumed.execute()
    checks('an incomplete set is never a confirmed capacity', result.search_status == 'unconfirmed_partial')
    checks('the incomplete run was not replayed', starts(sim) == len(sim.records()))


# ---- identity and reset ---------------------------------------------------------------------------

def stale_controller_is_refused_by_the_host_fence(sim, checks):
    stale = sim.executor(scorer=scorer(), failpoint=rf.crash_at('after_launching_commit'))
    try:
        stale.execute()
    except rf.SimulatedCrash:
        pass
    new, _ = sim.controller(scorer=scorer())
    new.prepare()
    trial = search.trial_from_dict(sim.records()[0]['trial'])
    plan = stale._plan(trial, 'game', sim.clock.wall() + 30, 100.0, sim.clock.wall() + 200)
    try:
        stale._runner('game', 'start', '--plan-json', json.dumps(plan))
        refused = False
    except run_executor.ControlLost as lost:
        refused = lost.code == 'stale_fence'
    checks('the host refused the start', refused)
    checks('nothing was launched', sim.guests.hosts['game'].runs == {})


def reused_process_identity_is_refused(sim, checks):
    original = sim.guests._do_start
    host = sim.guests.hosts['game']

    def replay(run_host, argv):
        if run_host is host and host.ledger:
            host.scripted_identity = dict(next(e for e in host.ledger if 'processes' in e)['processes']['game'])
        return original(run_host, argv)
    sim.guests._do_start = replay
    result = sim.executor(scorer=scorer({25: search.PASS})).execute()
    checks('the second run stopped as infrastructure', result.runs[-1]['outcome'] == search.INFRASTRUCTURE_FAILURE)
    checks('it names the earlier process', any('earlier process' in reason for reason in result.runs[-1]['reasons']))


def old_socket_counters_are_refused(sim, checks):
    original = sim.guests._do_start
    host = sim.guests.hosts['game']

    def reuse(run_host, argv):
        sealed = [e for e in host.ledger if e.get('sealed')]
        if run_host is host and sealed:
            host.scripted_inode = sealed[0]['socket_inodes'][0]
        return original(run_host, argv)
    sim.guests._do_start = reuse
    result = sim.executor(scorer=scorer({25: search.PASS})).execute()
    checks('the second run stopped as infrastructure', result.runs[-1]['outcome'] == search.INFRASTRUCTURE_FAILURE)
    checks('it names the earlier socket', any('earlier run' in reason for reason in result.runs[-1]['reasons']))


def leftover_socket_and_netem_stop_before_dispatch(sim, checks):
    sim.guests.hosts['game'].busy_ports.add(run_plan.GAME_PORT)
    sim.guests.hosts['bot'].qdiscs.append('netem')
    result = sim.executor(scorer=scorer()).execute()
    checks('both are named', 'still holds a socket' in result.detail and 'qdisc netem' in result.detail)
    checks('nothing was dispatched', sim.records() == [] and sim.guests.starts() == [])
    checks('the failure outlives this controller', sim.status_now()['terminal_failure'] == search.INFRASTRUCTURE_FAILURE)


def deadline_exhaustion_is_a_partial_search(sim, checks):
    crash_between_runs(sim)
    c = session_clock.parse(sim.status_now()['cleanup_c_utc'])
    sim.sleep(c - sim.clock.wall() - 1500)
    _, outcome = resume(sim)
    checks('resume is refused on the original headroom', outcome['code'] == 'headroom_exhausted')
    checks('nothing more ran', len(sim.records()) == 1)


# ---- resume eligibility ---------------------------------------------------------------------------

def eligible_resume_runs_only_untouched_work(sim, checks):
    crash_between_runs(sim)
    executor, outcome = resume(sim)
    checks('every revalidation passed', all(outcome['checks'][name] is True for name in registry.RESUME_REQUIRED_CHECKS))
    checks('it names the next untouched trial', outcome['next_run_id'].endswith('t02-coarse-n050-r1'))
    result = executor.execute()
    checks('the search finished with no replayed run', result.search_status == 'confirmed' and starts(sim) == len(sim.records()))


def _refused_when(change, expected):
    def scenario(sim, checks):
        crash_between_runs(sim)
        options = change(sim) or {}
        _, outcome = resume(sim, **options)
        checks('refused: ' + expected, (outcome['resumed'], outcome['code']) == (False, expected))
        checks('no run was added', len(sim.records()) == 1)
    return scenario


def _named(name, scenario):
    scenario.__name__ = name
    return scenario


def _terminal(sim):
    sim.client.mutate('record_batch_stop', session_id=sim.session_id, outcome=search.INFRASTRUCTURE_FAILURE, fencing_token=sim.result.fencing_token, detail='host failed')


def _abort(sim):
    sim.stack.registry.operator_abort(sim.session_id, 'operator abort')


def _past_c(sim):
    sim.sleep(session_clock.parse(sim.status_now()['cleanup_c_utc']) - sim.clock.wall() + 1)


def _changed_host(sim):
    sim.account.droplets[int(sim.result.droplets['game'])]['networks']['v4'][0]['ip_address'] = '198.51.100.222'


def _changed_source(sim):
    return dict(source_problems=lambda: ['the controller checkout is not the frozen controller revision'])


def _changed_binary(sim):
    sim.guests.hosts['bot'].file_overrides['/home/deploy/omega-release/omega-load-test'] = 'f' * 64


def _leftover(sim):
    sim.guests.hosts['game'].qdiscs.append('netem')


# ---- authority at the guest, demonstrated failures, recovery and cleanup ---------------------------

def _at(point, action):
    def failpoint(name):
        if name == point:
            action()
    return failpoint


def abort_before_authorization_starts_nothing(sim, checks):
    result = sim.executor(scorer=scorer(), failpoint=_at('after_launching_commit', lambda: _abort(sim))).execute()
    checks('the registry refused the authorization', result.status == run_executor.CLEANUP_STARTED)
    checks('no process started on either host', sim.guests.starts() == [])
    checks('the live controller closed both fences', all(sim.guests.hosts[role].fence['closed'] for role in ('game', 'bot')))
    checks('the run is incomplete, not replayed', outcomes(sim) == [search.INCOMPLETE])


def abort_in_flight_is_bounded_and_stopped_by_the_recheck(sim, checks):
    result = sim.executor(scorer=scorer(), failpoint=_at('after_game_authorized', lambda: _abort(sim))).execute()
    checks('a start authorized before the abort can land inside its window', starts(sim, 'game') == 1 and result.status == run_executor.CLEANUP_STARTED)
    checks('nothing further started', starts(sim, 'bot') == 0)
    run = next(iter(sim.guests.hosts['game'].runs.values()))
    checks('the recheck stopped it within the window', run.stop_at - run.started < registry.GUEST_ACTION_TTL_S)


def start_delayed_past_its_window_is_refused_by_the_guest(sim, checks):
    delay = lambda: sim.sleep(registry.GUEST_ACTION_TTL_S + 2)
    sim.executor(scorer=scorer(), failpoint=_at('after_game_authorized', delay)).execute()
    checks('no process and no directory', sim.guests.hosts['game'].runs == {})
    checks('the run is incomplete', outcomes(sim) == [search.INCOMPLETE])


def start_delayed_past_a_takeover_is_refused_by_the_fence(sim, checks):
    def takeover():
        sim.controller(scorer=scorer())[0].prepare()
    result = sim.executor(scorer=scorer(), failpoint=_at('after_game_authorized', takeover)).execute()
    checks('the host refused the old token', (result.status, result.code) == (run_executor.CONTROL_LOST, 'stale_fence'))
    checks('nothing was launched', sim.guests.hosts['game'].runs == {})


def _paused(sim):
    crash(sim, 'before_dispatch_commit')
    executor, control = sim.controller(scorer=scorer())
    executor.prepare()
    return executor, control


def smoke_delayed_past_a_takeover_is_refused_by_the_fence(sim, checks):
    old, _ = _paused(sim)
    arguments = old._authorized_arguments()
    new, _ = sim.controller(name='controller-c', scorer=scorer())
    new.prepare()
    try:
        old._agent('game', 'smoke_game_start', *arguments, '--smoke-id', 'delayed')
        code = None
    except run_executor.ControlLost as lost:
        code = lost.code
    checks('the guest refused the old token', code == 'stale_fence')
    checks('no server started', sim.guests.hosts['game'].smoke is None)


def smoke_delayed_past_its_window_is_refused_by_the_guest(sim, checks):
    executor, _ = _paused(sim)
    arguments = executor._authorized_arguments()
    sim.sleep(registry.GUEST_ACTION_TTL_S + 2)
    try:
        executor._agent('game', 'smoke_game_start', *arguments, '--smoke-id', 'delayed')
        refused = False
    except run_executor.GuestLost as lost:
        refused = 'authorization_expired' in str(lost)
    checks('the guest refused it', refused)
    checks('no server started', sim.guests.hosts['game'].smoke is None)


def lost_smoke_reply_reaches_the_stop(sim, checks):
    crash(sim, 'before_dispatch_commit')
    sim.guests.lost_answer.add(('game', 'smoke_game_start'))
    _, outcome = resume(sim)
    checks('resume refused with the original failure', outcome['code'] == 'GuestLost')
    checks('the stop still ran, by its fenced identity', sim.guests.hosts['game'].smoke is None and sim.guests.hosts['game'].smoke_stopped is not None)


def lost_smoke_reply_ends_by_itself_with_no_controller(sim, checks):
    crash(sim, 'before_dispatch_commit')
    sim.guests.lost_answer.add(('game', 'smoke_game_start'))
    sim.guests.unreachable.add(('game', 'smoke_game_stop'))
    _, outcome = resume(sim)
    host = sim.guests.hosts['game']
    checks('nothing could stop it', outcome['resumed'] is False and sim.guests.smoke_alive(host))
    sim.clock.advance(guest_agent.SMOKE_GAME_LIFETIME_S + 1)
    checks('its own lifetime released it', not sim.guests.smoke_alive(host))


def corrupt_export_then_crash_keeps_siblings_from_running(sim, checks):
    executor = sim.executor(scorer=scorer())
    hits = [0]

    def in_confirmation(name):
        if name == 'after_running_commit':
            hits[0] += 1
            if hits[0] == 4:
                sim.guests.corrupt_export.add('bot.stdout.log')
        if name == 'after_execution_record' and hits[0] == 4:
            raise rf.SimulatedCrash(name)
    executor.failpoint = in_confirmation
    try:
        executor.execute()
    except rf.SimulatedCrash:
        pass
    before = starts(sim)
    sim.guests.corrupt_export.clear()
    _, outcome = resume(sim)
    checks('the written-down failure stands', outcomes(sim)[-1] == search.INFRASTRUCTURE_FAILURE and sim.status_now()['terminal_failure'] == search.INFRASTRUCTURE_FAILURE)
    checks('the eligible sibling is refused', outcome['code'] == 'terminal_failure' and starts(sim) == before)


def failed_file_is_recovered_before_the_delete(sim, checks):
    sim.guests.corrupt_export.add('bot.stdout.log')
    executor = sim.executor()
    result = executor.execute()
    run_id = sim.records()[0]['run_id']
    checks('the seal arrived but the file did not', (sim.run_dir(run_id) / 'bot' / 'seal.json').exists() and (run_id, 'bot') in executor._collect_missing())
    sim.guests.corrupt_export.clear()
    executor.wrap_up(result)
    kinds = [event['kind'] for event in sim.stack.registry.journal(sim.session_id)]
    checks('recovery came before the cleanup intent', kinds.index('evidence_recovery') < kinds.index('cleanup_intent'))
    checks('the file is verified and the failure still stands', (sim.run_dir(run_id) / 'bot' / 'bot.stdout.log').exists() and outcomes(sim) == [search.INFRASTRUCTURE_FAILURE])


def local_collection_failure_still_requests_cleanup(sim, checks):
    executor = sim.executor()

    def full_disk():
        raise OSError('disk full')
    executor._collect_missing = full_disk
    result = executor.run_batch()
    checks('the original error is kept', 'disk full' in result.wrap_up_error)
    checks('cleanup intent is durable', sim.status_now()['cleanup']['requested_at'] is not None)


def wrong_controller_touches_nothing_on_a_first_run(sim, checks):
    before = len(sim.guests.commands)
    result = sim.executor(source_problems=lambda: ['the controller checkout is not the frozen controller revision']).run_batch()
    checks('refused', result.code == run_executor.SOURCE_CHANGED)
    checks('no guest was contacted', len(sim.guests.commands) == before and sim.guests.starts() == [])
    checks('the healthy pair is not deleted', sim.status_now()['cleanup']['requested_at'] is None)


SCENARIOS = (
    fresh_runs_reach_a_confirmed_observation, capacity_failure_advances_only_the_search, generator_crash_is_invalid_load, lost_host_is_a_terminal_infrastructure_failure,
    no_scorer_establishes_nothing, hung_workload_is_stopped_by_its_bound, crash_before_dispatch_keeps_the_trial_untouched, crash_after_dispatch_stops_the_dependent_path,
    crash_during_active_run_preserves_it, crash_before_outcome_keeps_the_verdict, crash_before_a_terminal_outcome_cannot_escape_it, crash_after_outcome_repairs_only_the_mirror,
    incomplete_confirmation_leaves_siblings_eligible, stale_controller_is_refused_by_the_host_fence, reused_process_identity_is_refused, old_socket_counters_are_refused,
    leftover_socket_and_netem_stop_before_dispatch, deadline_exhaustion_is_a_partial_search, eligible_resume_runs_only_untouched_work,
    _named('resume_refused_after_terminal_failure', _refused_when(_terminal, 'terminal_failure')),
    _named('resume_refused_after_operator_abort', _refused_when(_abort, 'cleanup_in_progress')),
    _named('resume_refused_after_c', _refused_when(_past_c, 'cleanup_in_progress')),
    _named('resume_refused_on_changed_host', _refused_when(_changed_host, 'pair_changed')),
    _named('resume_refused_on_changed_source', _refused_when(_changed_source, 'source_changed')),
    _named('resume_refused_on_changed_binary', _refused_when(_changed_binary, 'host_not_reset')),
    _named('resume_refused_on_uncleared_netem', _refused_when(_leftover, 'host_not_reset')),
    abort_before_authorization_starts_nothing, abort_in_flight_is_bounded_and_stopped_by_the_recheck, start_delayed_past_its_window_is_refused_by_the_guest,
    start_delayed_past_a_takeover_is_refused_by_the_fence, smoke_delayed_past_a_takeover_is_refused_by_the_fence, smoke_delayed_past_its_window_is_refused_by_the_guest,
    lost_smoke_reply_reaches_the_stop, lost_smoke_reply_ends_by_itself_with_no_controller, corrupt_export_then_crash_keeps_siblings_from_running, failed_file_is_recovered_before_the_delete,
    local_collection_failure_still_requests_cleanup, wrong_controller_touches_nothing_on_a_first_run,
)


def _trace(sim):
    events = []
    for event in sim.stack.registry.journal(sim.session_id):
        if event['kind'] in TRACE_EVENTS:
            data = event['data']
            brief = {k: data[k] for k in ('run_id', 'phase', 'outcome', 'reason', 'takeover', 'detail') if k in data}
            events.append(dict(kind=event['kind'], **brief))
    runs = [dict(run_id=r['run_id'], state=r['state'], phase=r['phase'], outcome=r['outcome'], interrupted_reason=r['interrupted_reason'], target=r['trial']['target'], kind=r['trial']['phase'])
            for r in sim.records()]
    status = sim.status_now()
    return dict(registry_events=events, runs=runs, session=dict(state=status['state'], terminal_failure=status['terminal_failure'], fencing_token=status['fencing_token']),
                host_starts=dict(game=starts(sim, 'game'), bot=starts(sim, 'bot')))


def run_scenario(scenario):
    context = fault_evidence.Context()
    try:
        sim = rf.RunSim(context)
        sim.ready()
        results = []
        scenario(sim, lambda name, passed: results.append(dict(check=name, passed=bool(passed))))
        failed = [r['check'] for r in results if not r['passed']]
        if failed:
            raise AssertionError(scenario.__name__ + ' failed: ' + ', '.join(failed))
        return dict(scenario=scenario.__name__, clock='scripted', remote='fake', scorer='scripted by the fixture, never a measurement', checks=results, **_trace(sim))
    finally:
        context.close()


def generate(out):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    summary = ['# Slice 4 offline run timelines', '',
               'Generated by `scripts/do_session/run_fault_evidence.py`: the real executor, registry and watchdog against a fake remote on a scripted clock. No account, network, credential, guest, '
               'workload or measurement was involved. Outcomes come from a scripted fixture because no scorer exists yet, so none of this is a capacity result. Real local process behaviour is covered '
               'by `test_guest_runner` and `test_run_local_integration`, which are not retained here because process ids are not reproducible. `test_run_fault_evidence` regenerates these files and compares '
               'them with `SHA256SUMS`.', '', '| Timeline | Checks passed | Runs | Final session state |', '| --- | ---: | ---: | --- |']
    sums = []
    for scenario in SCENARIOS:
        result = run_scenario(scenario)
        hits = manifest_mod.scan_for_secrets(result)
        if hits:
            raise AssertionError('credential-like value in ' + scenario.__name__ + ': ' + ', '.join(hits))
        text = json.dumps(result, indent=1, sort_keys=True) + '\n'
        name = scenario.__name__ + '.json'
        (out / name).write_text(text, encoding='utf-8')
        sums.append(hashlib.sha256(text.encode('utf-8')).hexdigest() + '  ' + name)
        summary.append('| [%s](%s) | %d/%d | %d | %s |' % (scenario.__name__, name, sum(1 for c in result['checks'] if c['passed']), len(result['checks']), len(result['runs']), result['session']['state']))
    (out / 'README.md').write_text('\n'.join(summary) + '\n', encoding='utf-8')
    sums.append(hashlib.sha256((out / 'README.md').read_bytes()).hexdigest() + '  README.md')
    (out / 'SHA256SUMS').write_text('\n'.join(sorted(sums, key=lambda line: line.split()[1])) + '\n', encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', required=True)
    generate(parser.parse_args(argv).out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
