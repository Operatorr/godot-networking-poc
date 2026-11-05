#!/usr/bin/env python3
"""Regenerate the retained evidence for handoff slice 6 (issue #69).

    scoring_evidence.py synthetic --out D      the real scorer over mocked recorder files, and whole searches through the real executor over a fake guest. Byte-reproducible, and ``test_scoring_evidence`` checks it.
    scoring_evidence.py real --out D --release R    real binaries on loopback, one machine. Not reproducible: ``SHA256SUMS`` only says these are the bytes retained. Run it under ``measurement_offline.sb``.

Nothing here is a capacity finding. Each synthetic number is arithmetic, and each real run ran on one laptop with one wall clock and no per-socket counters.
"""
import argparse
import hashlib
import json
import pathlib
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest

import capacity_report
import capacity_scorer as cs
import measurement_local as ml
import measurement_window as mw
import run_executor
import run_fixtures as rf
import scoring_fixtures as sf
import search

NS = mw.NS
HERE = pathlib.Path(__file__).parent
REPO = HERE.parents[1]
NOTE_SYNTHETIC = 'Synthetic. Nothing ran: every tree is mocked recorder files, and each "60 s window" is arithmetic. It shows what the real scorer does with those bytes and says nothing about any host. Not a capacity observation.'
NOTE_REAL = 'Real processes on one macOS machine in real time, over loopback, with one wall clock and no per-socket counters. Never a live-host validation and not a capacity observation: a counter-required production proof stays inconclusive here.'


def _tight_slow(count, work_ns=40_000_000):
    def change(tree):
        sf.tight_clocks(tree)
        sf.set_slow_ticks(tree, count, work_ns)
    return change


def _all_work(work_ns):
    def change(tree):
        sf.tight_clocks(tree)
        rows = sf.tick_rows(tree)
        for row in rows[1:]:
            row[3] = str(work_ns)
        sf.write_ticks(tree, rows)
    return change


def _wide_slow(count):
    def change(tree):
        sf.tight_clocks(tree, half_ns=900_000_000)
        sf.set_slow_ticks(tree, count, 40_000_000)
    return change


def _crash(tree):
    sf.game_died(tree, 30)
    sf.bots_time_out_after_game_died(tree, [1, 2], 35)


def _ramp(reason='readiness_timeout', authenticated=5, then=None):
    def change(tree):
        sf.ramp_failure(tree, reason, authenticated)
        if then is not None:
            then(tree)
    return change


def _bot_counter_missing(index, row):
    for item in row['procs']['bot']['sockets']:
        item['drops'] = None


def _tick_gone(tree):
    rows = sf.tick_rows(tree)
    rows[sf.ticks_in_window(tree, rows)[100]][4] = str(tree.timeline.target - 1)
    sf.write_ticks(tree, rows)


def _pool_slow(count):
    def change(tree):
        seen = []

        def value(bot, second):
            seen.append(1)
            return 500 if len(seen) <= count else 12.5
        sf.set_rtt(tree, value)
    return change


# name, Tree options, how to change it, what the executor's sealed record says
SCENARIOS = (
    ('valid_pass_60s', {}, None, None),
    ('valid_pass_300s_confirmation_window', dict(hold_s=300), None, None),
    # thresholds, each side of each line
    ('tick_of_exactly_33_3_ms_is_not_above', {}, _all_work(33_300_000), None),
    ('exactly_1_percent_of_ticks_over_fails', {}, _tight_slow(18), None),
    ('one_tick_under_1_percent_passes', {}, _tight_slow(17), None),
    ('tick_ratio_depends_on_clock_position', {}, _wide_slow(18), None),
    ('rtt_exactly_150_ms_fails', {}, lambda t: sf.set_rtt(t, lambda bot, second: 150), None),
    ('rtt_149_999_ms_passes', {}, lambda t: sf.set_rtt(t, lambda bot, second: 149.999), None),
    ('rtt_24_of_480_samples_high_passes_nearest_rank', {}, _pool_slow(24), None),
    ('rtt_25_of_480_samples_high_fails_nearest_rank', {}, _pool_slow(25), None),
    ('rtt_three_slow_bots_fail_the_pool_while_a_per_bot_average_would_pass', {}, lambda t: sf.set_rtt(t, lambda bot, second: 200 if bot <= 3 else 12.5), None),
    ('rtt_two_bots_briefly_slow_pass_the_pool_while_a_per_bot_average_would_fail', {}, lambda t: sf.set_rtt(t, lambda bot, second: 1000 if bot <= 2 and second < 4 else 12.5), None),
    ('rtt_sample_missing_is_not_fast', {}, lambda t: sf.edit_peer_samples(t, lambda bot, second, sample: None if bot == 3 else sample), None),
    ('loss_exactly_2_percent_in_one_second_fails', dict(target=25), lambda t: sf.set_loss(t, lambda bot, second: 32768 if bot == 1 and second == 7 else 0), None),
    ('loss_just_under_2_percent_passes', dict(target=25), lambda t: sf.set_loss(t, lambda bot, second: 32767 if bot == 1 and second == 7 else 0), None),
    ('loss_one_second_excursion_fails_a_fine_average', {}, lambda t: sf.set_loss(t, lambda bot, second: 3000 if second == 30 else 0), None),
    ('loss_one_bot_high_is_a_peer_peak_and_no_gate', {}, lambda t: sf.set_loss(t, lambda bot, second: 6554 if bot == 1 else 0), None),
    ('loss_gap_too_long_to_borrow_across', {}, lambda t: sf.edit_peer_samples(t, lambda bot, second, sample: None if bot == 1 and 10 <= second < 16 else sample), None),
    ('game_socket_drop_inside_the_window', {}, lambda t: sf.game_drop(t, 30, count=3), None),
    ('game_socket_drop_at_the_uncertain_edge', {}, sf.game_drop_before_any_window_read, None),
    ('game_socket_counter_missing_is_not_zero', {}, sf.foggy, None),
    ('input_exactly_99_percent_valid', {}, lambda t: t.edit_frozen_bot(3, lambda row: row.update(scheduled=1800, sent=1782)), None),
    ('input_one_frame_below_99_percent_invalid', {}, lambda t: t.edit_frozen_bot(3, lambda row: row.update(scheduled=1800, sent=1781)), None),
    ('generator_socket_drop_invalid', {}, lambda t: sf.bot_drop(t, 2), None),
    ('generator_socket_counter_missing_is_not_zero', {}, lambda t: t.edit_sampler('bot', _bot_counter_missing), None),
    ('bot_panic_invalid', {}, lambda t: t.edit_frozen_bot(1, lambda row: row.update(panics=1)), None),
    ('decode_failure_cause_unknown', {}, lambda t: t.edit_frozen_bot(1, lambda row: row.update(decode_failures=1)), None),
    # who caused it
    ('server_kick_with_a_healthy_generator', {}, lambda t: sf.lose_bot(t, 2, 30, cs.REASON_KICKED), None),
    ('server_kick_after_independent_starvation', {}, lambda t: sf.lose_bot(t, 2, 30, cs.REASON_KICKED, sent=0), None),
    ('server_kick_seen_late_with_frames_missing_only_after_it', {}, lambda t: sf.lose_bot(t, 2, 1.4, cs.REASON_KICKED, server_at_s=1.0, sent=30), None),
    ('server_kick_seen_late_with_starvation_before_it', {}, lambda t: sf.lose_bot(t, 2, 1.4, cs.REASON_KICKED, server_at_s=1.0, sent=10), None),
    ('transport_timeout_with_nothing_else_wrong', {}, lambda t: sf.lose_bot(t, 2, 30, 0), None),
    ('transport_timeout_beside_tick_overrun', {}, lambda t: (sf.lose_bot(t, 2, 30, 0), sf.set_slow_ticks(t, 180, 40_000_000)), None),
    ('server_shutdown_reason_is_no_capacity_signal', {}, lambda t: sf.lose_bot(t, 2, 30, cs.REASON_SERVER_SHUTDOWN), None),
    ('duplicate_session_reason_is_no_capacity_signal', {}, lambda t: sf.lose_bot(t, 2, 30, 5), None),
    ('server_saw_a_departure_the_bot_did_not', {}, lambda t: sf.server_row_only(t, 2, 30), None),
    ('population_below_n_with_no_account_of_who', {}, _tick_gone, None),
    ('poll_starvation_alone', {}, lambda t: t.edit_shard_row(1, 'footer', lambda r: r.update(max_poll_gap_ns=501_000_000)), None),
    ('poll_starvation_beside_a_tick_overrun', {}, lambda t: (t.edit_shard_row(1, 'footer', lambda r: r.update(max_poll_gap_ns=501_000_000)), sf.set_slow_ticks(t, 180, 40_000_000)), None),
    ('game_panic_mid_window', {}, _crash, sf.execution(game_exit=(101, None))),
    ('game_segfault_mid_window', {}, _crash, sf.execution(game_exit=(None, 11))),
    ('game_sigkill_with_no_cause_on_record', {}, _crash, sf.execution(game_exit=(None, 9))),
    ('game_exit_0_mid_window', {}, _crash, sf.execution(game_exit=(0, None))),
    ('host_rebooted', {}, sf.rebooted, None),
    # a ramp that never held N
    ('ramp_readiness_timeout_alone', {}, _ramp(), None),
    ('ramp_timeout_beside_a_proven_overrun', {}, _ramp(then=lambda t: sf.ramp_slow_ticks(t, 2)), None),
    ('ramp_kick', {}, _ramp('bot_failed_before_window', then=lambda t: sf.add_bot_end(t, 3, 'server disconnected (reason 2)', dict(at_ns=2 * NS, reason=cs.REASON_KICKED, expected=False))), None),
    ('ramp_transport_timeout_alone', {}, _ramp('bot_failed_before_window', then=lambda t: sf.add_bot_end(t, 3, 'server disconnected (reason 0)', dict(at_ns=2 * NS, reason=0, expected=False))), None),
    ('ramp_poll_starvation', {}, _ramp(then=lambda t: t.edit_shard_row(1, 'footer', lambda r: r.update(max_poll_gap_ns=600_000_000))), None),
    ('ramp_starvation_beside_an_overrun', {}, _ramp(then=lambda t: (t.edit_shard_row(1, 'footer', lambda r: r.update(max_poll_gap_ns=600_000_000)), sf.ramp_slow_ticks(t, 2))), None),
    ('ramp_generator_counters_unproven', {}, _ramp(then=lambda t: (t.edit_sampler('bot', _bot_counter_missing), sf.ramp_slow_ticks(t, 2))), None),
    # evidence that may not be scored at all
    ('foreign_swarm_schema_with_slow_ticks', {}, lambda t: (t.edit_json('bot/swarm/swarm.json', lambda d: d.update(schema='omega.measurement/2')), sf.set_slow_ticks(t, 180, 40_000_000)), None),
    ('fault_build_with_nothing_injected', {}, lambda t: t.edit_json('bot/swarm/swarm.json', lambda d: d.update(build=dict(fault_injection=True))), None),
    ('swarm_told_to_stop_in_the_window', {}, lambda t: t.edit_json('bot/swarm/window.json', lambda d: d.update(status='window_incomplete', reason='interrupted')), None),
)
BYPASSES = (
    ('local_counter_bypass', dict(require_counters=False)),
    ('prover_never_given_the_schema', dict(prove=dict(telemetry_schema=None))),
    ('historical_placeholder_manifest', dict(placeholder=True)),
    ('short_hold_the_prover_was_allowed', dict(tree=dict(hold_s=5), prove=dict(allow_short_hold=True))),
)


def score_scenarios():
    rows = {}
    for name, options, change, record in SCENARIOS:
        with tempfile.TemporaryDirectory(prefix='omega-score-') as root:
            scenario = sf.Scenario(root, **options)
            if change is not None:
                change(scenario.tree)
            rows[name] = sf.summary(scenario.score(execution_record=record))
    for name, options in BYPASSES:
        with tempfile.TemporaryDirectory(prefix='omega-score-') as root:
            scenario = sf.Scenario(root, **options.get('tree', {}))
            prove = dict(options.get('prove', {}))
            if 'require_counters' in options:
                prove['require_counters'] = options['require_counters']
            if options.get('placeholder'):
                placeholder = dict(id='omega.measurement/2', sha256='a' * 64)
                document = scenario.score(telemetry_schema=placeholder, proof=scenario.proof(telemetry_schema=placeholder))
            else:
                document = scenario.score(proof=scenario.proof(**prove))
            rows[name] = sf.summary(document)
    return rows


# ---- whole searches -------------------------------------------------------------------------------

class _Case(unittest.TestCase):
    """The simulator takes a test case for its cleanups. Here they run when the search has been summarized."""

    def runTest(self):
        pass


def _search_summary(sim, result, extra=None):
    report = capacity_report.build(sim.stack.root)
    starts = len([call for call in sim.guests.calls if call['command'] == 'start' and call['role'] == 'game'])
    return dict(status=report['status'], claim=report['claim'], batch=result.status if result is not None else None, observations=report['observations'], counts=report['counts'], game_starts=starts, no_hidden_retry=starts == len(sim.records()),
                trials=[{key: row.get(key) for key in ('ordinal', 'phase', 'target', 'repetition', 'hold_s', 'outcome', 'classification', 'gates', 'offered_load')} for row in report['trials']], **(extra or {}))


def _plain(rules, **options):
    def play(case):
        sim = sf.ScoredSim(case, sf.by_target(rules), **options)
        case.addCleanup(rf.make_writable, sim.stack.root)
        sim.ready()
        return sim, sim.executor().execute(), None
    return play


def _confirmation_fails_at(repetition, change=sf.slow):
    seen = []

    def confirmation(tree):
        seen.append(1)
        if len(seen) == repetition:
            change(tree)
    return _plain({50: sf.slow, 30: sf.slow, ('confirm', 25): confirmation})


def _crash_in_coarse(point, rules=None):
    def play(case):
        sim = sf.ScoredSim(case, sf.by_target({50: sf.slow, 30: sf.slow} if rules is None else rules))
        case.addCleanup(rf.make_writable, sim.stack.root)
        sim.ready()
        try:
            sim.executor(failpoint=rf.crash_at(point)).execute()
        except rf.SimulatedCrash:
            pass
        executor, control = sim.controller()
        outcome = executor.resume('operator: resume remaining runs', control)
        result = executor.run_batch() if outcome['resumed'] else None
        return sim, result, dict(crashed_at=point, resumed=outcome['resumed'], resume_code=outcome.get('code'))
    return play


def _interrupted_confirmation(case):
    sim = sf.ScoredSim(case, sf.by_target({50: sf.slow, 30: sf.slow}))
    case.addCleanup(rf.make_writable, sim.stack.root)
    sim.ready()
    count = dict(n=0)

    def in_confirmation(name):
        if name == 'after_running_commit':
            count['n'] += 1
            if count['n'] == 4:
                raise rf.SimulatedCrash(name)
    try:
        sim.executor(failpoint=in_confirmation).execute()
    except rf.SimulatedCrash:
        pass
    executor, control = sim.controller()
    outcome = executor.resume('operator: resume remaining runs', control)
    return sim, executor.execute(), dict(crashed_at='after_running_commit in the first confirmation', resumed=outcome['resumed'], resume_code=outcome.get('code'))


def _time_exhausted(case):
    sim = sf.ScoredSim(case)
    case.addCleanup(rf.make_writable, sim.stack.root)
    sim.ready()
    ran = []

    def third_selection(name):
        if name == 'after_selection':
            ran.append(1)
            if len(ran) == 3:
                raise rf.SimulatedCrash(name)
    try:
        sim.executor(failpoint=third_selection).execute()
    except rf.SimulatedCrash:
        pass
    c = run_executor.session_clock.parse(sim.status_now()['cleanup_c_utc'])
    sim.sleep(c - sim.clock.wall() - 1800)
    token = sim.client.acquire(sim.session_id, takeover=True)['fencing_token']
    state = run_executor.state_from_records(sim.session_id, sim.records())
    sim.client.mutate('record_resume', session_id=sim.session_id, fencing_token=token, operator_request_ref='fixture',
                      checks={**{name: True for name in rf.registry.RESUME_REQUIRED_CHECKS}, 'manifest_sha256': sim.sha, 'next_run_id': search.next_trial(state).run_id})
    return sim, sim.executor(token=token).execute(), None


def _kick_at_50():
    return _plain({50: lambda tree: sf.lose_bot(tree, 2, 30, cs.REASON_KICKED), 30: sf.slow})


def _ramp_overrun_at_50():
    def ramp(tree):
        sf.ramp_failure(tree, 'readiness_timeout', tree.timeline.target - 1)
        sf.ramp_slow_ticks(tree, 2)
    return _plain({50: ramp, 30: sf.slow})


SEARCHES = (
    ('confirmed', _plain({50: sf.slow, 30: sf.slow})),
    ('refinement_all_pass_confirms_top_of_bracket', _plain({50: sf.slow})),
    ('first_rung_failure_then_5_fails', _plain({25: sf.slow, 5: sf.slow})),
    ('first_rung_failure_candidate_under_it', _plain({25: sf.slow, 10: sf.slow})),
    ('first_rung_failure_all_refinements_pass', _plain({25: sf.slow})),
    ('all_coarse_pass_search_cap_at_500', _plain({}, cap_s=7 * 3600)),
    ('confirmation_1_fails', _confirmation_fails_at(1)),
    ('confirmation_2_fails', _confirmation_fails_at(2)),
    ('confirmation_3_fails', _confirmation_fails_at(3)),
    ('confirmation_2_invalid_load_stops', _confirmation_fails_at(2, sf.starved)),
    ('confirmation_3_inconclusive_stops', _confirmation_fails_at(3, sf.foggy)),
    ('confirmation_1_interrupted_siblings_run_set_stays_partial', _interrupted_confirmation),
    ('coarse_invalid_load_stops', _plain({50: sf.starved})),
    ('coarse_inconclusive_stops', _plain({50: sf.foggy})),
    ('coarse_infrastructure_stops', _plain({50: sf.rebooted})),
    ('refine_invalid_load_stops', _plain({50: sf.slow, 30: sf.starved})),
    ('refine_inconclusive_stops', _plain({50: sf.slow, 30: sf.foggy})),
    ('first_rung_invalid_load_stops_with_no_claim', _plain({25: sf.starved})),
    ('server_disconnect_opens_the_bracket', _kick_at_50()),
    ('ramp_overrun_opens_the_bracket', _ramp_overrun_at_50()),
    ('interrupted_active_trial_is_never_replayed', _crash_in_coarse('after_running_commit')),
    ('natural_end_found_on_return_is_scored_then_resumes', _crash_in_coarse('after_execution_record')),
    ('retained_score_is_read_on_return', _crash_in_coarse('after_score_retained')),
    ('verdict_before_outcome_commit_is_kept', _crash_in_coarse('before_outcome_commit', rules={25: sf.slow, 5: sf.slow})),
    ('terminal_fact_committed_before_crash_refuses_resume', _crash_in_coarse('after_outcome_commit', rules={25: sf.starved})),
    ('time_exhausted_keeps_partial_results', _time_exhausted),
)


def search_scenarios():
    rows = {}
    for name, play in SEARCHES:
        case = _Case()
        try:
            sim, result, extra = play(case)
            rows[name] = _search_summary(sim, result, extra)
        finally:
            case.doCleanups()
    return rows


def synthetic(out):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    frozen = dict(measurement_schema=mw.schema()['id'], measurement_schema_sha256=mw.schema_sha256(), scorer=cs.SCORER, policy=cs.POLICY, policy_sha256=cs.POLICY_SHA256)
    (out / 'synthetic-scores.json').write_text(json.dumps(dict(schema='omega.do-session.score-evidence/1', kind='synthetic', note=NOTE_SYNTHETIC, scenarios=score_scenarios(), **frozen), indent=1, sort_keys=True) + '\n')
    (out / 'synthetic-searches.json').write_text(json.dumps(dict(schema='omega.do-session.search-evidence/1', kind='synthetic', note=NOTE_SYNTHETIC + ' Outcomes are not scripted: each comes from the real prover and scorer over the bytes the fake guest exported.', scenarios=search_scenarios(), **frozen), indent=1, sort_keys=True) + '\n')


# ---- real binaries --------------------------------------------------------------------------------

def real_evidence(run, proof):
    """What the executor would hand the scorer, from a real local run. The ``require_counters=False`` the local prover needs on this platform is exactly what the scorer refuses, so no run here can pass."""
    results = run['results']
    execution = dict(problems=dict(infrastructure=[], generator=[], game=[]), roles={role: dict(result=(result or {}).get('result')) for role, result in results.items()},
                     exported={role: dict(complete=True, failed=[]) for role in results}, interrupted=None)
    return dict(run_id=run['trial']['run_id'], trial=run['trial'], root=run['evidence'], execution=execution, execution_sha256=None, execution_ref='local', window_proof=proof, window_proof_sha256='local', workload=run['workload'], telemetry_schema=sf.FROZEN_SCHEMA)


def _block_one_bot_in_window(index, offset_s):
    """Swallow one bot's traffic both ways, from inside the hold on. Neither binary knows why it went quiet, so what each records is what a real path failure would leave."""
    def step(run):
        if run.await_publication() is not None:
            import time
            time.sleep(1.0 + offset_s)
            run.relay.hold(index, None)
    return step


REAL = (
    ('contract_60s_25_bots', dict(target=25, hold_s=60), dict(allow_short_hold=False)),
    ('short_complete_8_bots', dict(target=8, hold_s=6), {}),
    ('one_bot_path_blocked_mid_window', dict(target=8, hold_s=20, use_relay=True, schedule=[_block_one_bot_in_window(2, 2.0)]), {}),
    ('game_killed_mid_window', dict(target=8, hold_s=20, schedule=[ml.FaultSchedule.kill_game_in_window(2.0)]), {}),
    ('swarm_paused_mid_window', dict(target=8, hold_s=6, schedule=[ml.FaultSchedule.pause_swarm_in_window(1.5)]), {}),
    ('authentication_never_arrives', dict(target=8, hold_s=6, use_relay=True, schedule=[ml.FaultSchedule.hold_one_bot(2, None)], readiness_timeout_s=4.0), {}),
)


def provenance(release):
    def run(*argv):
        return subprocess.run(argv, stdout=subprocess.PIPE, check=True, cwd=str(REPO)).stdout.decode().strip()
    return dict(source_revision=run('git', 'rev-parse', 'HEAD'), source_clean=not run('git', 'status', '--porcelain'), source_tree=run('git', 'rev-parse', 'HEAD^{tree}'), python=platform.python_version(), platform=platform.platform(), measurement_schema=mw.schema()['id'], measurement_schema_sha256=mw.schema_sha256(),
                scorer=cs.SCORER, policy_sha256=cs.POLICY_SHA256, cargo_lock_sha256=hashlib.sha256((REPO / 'rust/Cargo.lock').read_bytes()).hexdigest(), server_config_sha256=hashlib.sha256((REPO / 'deployment/server_config.loadtest.json').read_bytes()).hexdigest(),
                binaries=dict(omega_server=hashlib.sha256((pathlib.Path(release) / 'omega-server').read_bytes()).hexdigest(), omega_load_test=hashlib.sha256((pathlib.Path(release) / 'omega-load-test').read_bytes()).hexdigest()))


def real(out, release):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    scenarios = {}
    root = pathlib.Path(tempfile.mkdtemp(prefix='omega-score-real-'))
    try:
        for name, options, prove in REAL:
            options = dict(options)
            run = ml.LocalRun(release, root / name, options.pop('target'), options.pop('hold_s'), **options).execute()
            proof = ml.prove(run, telemetry_schema=sf.FROZEN_SCHEMA, **prove)
            document = cs.evaluate(real_evidence(run, proof))
            row = sf.summary(document)
            row.update(events=run['events'], exits={role: (result.get('result') or {}).get('processes') for role, result in run['results'].items()}, proof_contract_hold=(proof.get('facts') or {}).get('contract_hold'), clock_half_width_ms=document['diagnostics']['clock_half_width_ms'])
            scenarios[name] = row
            print(name, row['classification'], row['proof_reasons'], {key: value['verdict'] for key, value in row['gates'].items()}, flush=True)
    finally:
        shutil.rmtree(str(root), True)
    (out / 'real-local-scores.json').write_text(json.dumps(dict(schema='omega.do-session.score-evidence/1', kind='real_local', note=NOTE_REAL, provenance=provenance(release), scenarios=scenarios), indent=1, sort_keys=True) + '\n')


def write_sums(out):
    out = pathlib.Path(out)
    lines = ['%s  %s\n' % (hashlib.sha256(path.read_bytes()).hexdigest(), path.name) for path in sorted(out.glob('*.json'))]
    (out / 'SHA256SUMS').write_text(''.join(lines))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('kind', choices=('synthetic', 'real'))
    parser.add_argument('--out', required=True)
    parser.add_argument('--release', help='a directory holding omega-server and omega-load-test')
    args = parser.parse_args(argv)
    if args.kind == 'real':
        if not args.release:
            parser.error('real needs --release')
        real(args.out, args.release)
    else:
        synthetic(args.out)
    write_sums(args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
