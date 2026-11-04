"""The real executor over a fake remote, on the scripted clock: full lifecycles, every crash window and every resume rule."""
import json
import pathlib
import unittest

import admission
import fake_guest
import guest_runner
import registry
import registry_client
import run_checks
import run_executor
import run_fixtures as rf
import run_plan
import search
import session_clock

ALL_PASS_THEN_FAIL_50 = {25: search.PASS, 50: search.FAIL}


class Base(unittest.TestCase):
    def setUp(self):
        self.sim = rf.RunSim(self)
        self.addCleanup(rf.make_writable, self.sim.stack.root)
        self.sim.ready()
        self.guests = self.sim.guests

    def scorer(self, outcomes=None, default=search.PASS):
        return rf.scripted_scorer(outcomes if outcomes is not None else ALL_PASS_THEN_FAIL_50, default)

    def live_outcomes(self):
        return [(r['run_id'].split('-t', 1)[1], r['outcome']) for r in self.sim.records()]

    def state(self):
        return self.sim.status_now()['state']

    def terminal(self):
        return self.sim.status_now()['terminal_failure']

    def crash_run(self, point, scorer=None):
        """One controller dies at ``point``. The fixture's clock and the watchdog carry on."""
        executor = self.sim.executor(scorer=scorer or self.scorer(), failpoint=rf.crash_at(point))
        with self.assertRaises(rf.SimulatedCrash):
            executor.execute()
        return executor

    def come_back(self, scorer=None, **options):
        return self.sim.controller(scorer=scorer or self.scorer(), **options)

    def resume(self, scorer=None, operator='operator: resume remaining runs', **options):
        executor, control = self.come_back(scorer, **options)
        return executor, executor.resume(operator, control)


class FreshRuns(Base):
    def test_a_whole_search_uses_one_pair_and_fresh_everything(self):
        droplets = self.sim.session_droplets()
        result = self.sim.executor(scorer=self.scorer()).execute()
        self.assertEqual((result.status, result.search_status), (run_executor.FINISHED, 'confirmed'))
        self.assertEqual(self.sim.session_droplets(), droplets, 'the pair is reused')
        self.assertEqual(len(self.sim.creates('/v2/droplets')), 2, 'no replacement host')
        starts = self.guests.starts()
        self.assertEqual(len(starts), 2 * len(result.runs))
        ledger = self.guests.hosts['game'].ledger
        identities = [(e['processes']['game']['pid'], e['processes']['game']['start_id']) for e in ledger if 'processes' in e]
        self.assertEqual(len(identities), len(set(identities)))
        sockets = [e['socket_inodes'][0] for e in ledger if e.get('sealed')]
        self.assertEqual(len(sockets), len(set(sockets)))
        for row in result.runs:
            run_dir = self.sim.run_dir(row['run_id'])
            for name in ('selected.json', 'grant.json', 'plan-game.json', 'plan-bot.json', 'execution.json', 'classification.json', 'game/seal.json', 'bot/seal.json', 'bot/report.json'):
                self.assertTrue((run_dir / name).exists(), name)

    def test_outcomes_advance_only_the_frozen_search(self):
        result = self.sim.executor(scorer=self.scorer({25: search.PASS, 50: search.FAIL, 30: search.FAIL})).execute()
        self.assertEqual([r['outcome'] for r in result.runs], [search.PASS, search.FAIL, search.FAIL, search.PASS, search.PASS, search.PASS])
        self.assertEqual(result.search_status, 'confirmed')
        confirm = [r['run_id'] for r in result.runs if '-confirm-' in r['run_id']]
        self.assertEqual(len(confirm), 3)
        self.assertTrue(all('n025' in run_id for run_id in confirm))

    def test_the_plan_is_exactly_the_frozen_workload(self):
        self.sim.executor(scorer=self.scorer({25: search.FAIL, 5: search.FAIL})).execute()
        first = self.sim.records()[0]['run_id']
        bot = json.loads((self.sim.run_dir(first) / 'plan-bot.json').read_text())
        argv = bot['processes'][0]['argv']
        for flag, value in (('--bots', '25'), ('--duration', '60'), ('--behavior', 'strategy'), ('--difficulty', '1.0'), ('--input-hz', '30'), ('--seed', '1'), ('--threads', '4'), ('--stagger', '100')):
            self.assertEqual(argv[argv.index(flag) + 1], value)
        game = json.loads((self.sim.run_dir(first) / 'plan-game.json').read_text())
        self.assertEqual(game['verify_files'][0]['sha256'], self.sim.manifest['source']['binary_sha256']['game'])
        self.assertEqual(game['verify_files'][1]['sha256'], self.sim.manifest['source']['server_config_sha256'])
        self.assertEqual(bot['verify_files'][0]['sha256'], self.sim.manifest['source']['binary_sha256']['bot'])

    def test_process_bounds_end_before_the_grant_would(self):
        self.sim.executor(scorer=self.scorer()).execute()
        timing = self.sim.manifest['timing_basis']
        reserved = timing['recorder_finalization_s']['seconds'] + timing['per_trial_export_s']['seconds']
        for row in self.sim.records():
            trial = search.trial_from_dict(row['trial'])
            must_stop = session_clock.parse(row['must_stop_by'])
            for role in ('game', 'bot'):
                plan = json.loads((self.sim.run_dir(row['run_id']) / ('plan-%s.json' % role)).read_text())
                self.assertLessEqual(plan['stop_by_wall'], must_stop - reserved)
                self.assertGreaterEqual(plan['bound_s'], run_plan.workload_s(trial))
                self.assertLessEqual(plan['launch_not_after_wall'], session_clock.parse(row['launch_by']) + run_executor.Policy().game_start_wait_s)

    def test_lease_is_kept_alive_through_a_long_confirmation_run(self):
        self.sim.executor(scorer=self.scorer({25: search.PASS, 50: search.FAIL, 30: search.FAIL})).execute()
        self.assertEqual(self.sim.status_now()['fencing_token'], self.sim.result.fencing_token, 'no lapse or takeover happened')
        self.assertEqual(self.state(), registry.READY)

    def test_with_no_scorer_a_finished_run_establishes_nothing(self):
        result = self.sim.executor().execute()
        self.assertEqual(len(result.runs), 1)
        self.assertEqual(result.runs[0]['outcome'], search.INCONCLUSIVE)
        self.assertEqual(result.search_status, 'stopped_inconclusive_evidence')
        self.assertEqual(self.terminal(), search.INCONCLUSIVE)

    def test_journal_mirror_matches_the_registry(self):
        result = self.sim.executor(scorer=self.scorer()).execute()
        path = self.sim.stack.root / 'search_journal.ndjson'
        entries = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual([e['run_id'] for e in entries if e['kind'] == 'outcome'], [r['run_id'] for r in result.runs])
        self.assertEqual([e['trial']['run_id'] for e in entries if e['kind'] == 'selected'], [r['run_id'] for r in result.runs])

    def test_wrap_up_collects_then_asks_for_deletion(self):
        result = self.sim.executor(scorer=self.scorer()).run_batch()
        self.assertEqual(result.search_status, 'confirmed')
        final = self.sim.drive_cleanup()
        self.assertEqual(final['measurement']['outcome'], 'confirmed')
        self.assertEqual(final['evidence']['status'], 'partial', 'the session-level export is slice 7, so nothing may read clean yet')
        self.assertEqual(final['overall'], 'resources_verified_evidence_incomplete')


class Classification(Base):
    """Which failures advance the search, and which stop it. A timeout or a crash alone is never called capacity."""

    def outcome_of_first_run(self, scorer=None):
        result = self.sim.executor(scorer=scorer or self.scorer()).execute()
        return result, result.runs[0]

    def test_attributable_game_failure_needs_a_scorer_and_advances_only_the_search(self):
        self.guests.game_crash_after_s = 20.0
        result = self.sim.executor(scorer=self.scorer({25: search.FAIL, 5: search.FAIL})).execute()
        self.assertEqual(result.runs[0]['outcome'], search.FAIL)
        self.assertIsNone(self.terminal(), 'a capacity failure with a valid generator is not terminal')
        self.assertEqual(result.search_status, 'no_passing_target')

    def test_a_crashed_game_with_no_scorer_is_not_called_capacity(self):
        self.guests.game_crash_after_s = 20.0
        _, row = self.outcome_of_first_run(rf.scripted_scorer(default=None))
        self.assertEqual(row['outcome'], search.INCONCLUSIVE)

    def test_a_scorer_cannot_pass_a_run_whose_game_crashed(self):
        self.guests.game_crash_after_s = 20.0
        result, row = self.outcome_of_first_run(self.scorer({25: search.PASS}))
        self.assertEqual(row['outcome'], search.INCONCLUSIVE)
        self.assertIn('a PASS cannot stand on a run whose processes failed', row['reasons'])
        self.assertEqual(self.terminal(), search.INCONCLUSIVE)

    def test_a_crashed_generator_is_invalid_load_and_never_reaches_a_scorer(self):
        self.guests.bot_exit = (77, None)
        scorer = self.scorer({25: search.FAIL})
        result, row = self.outcome_of_first_run(scorer)
        self.assertEqual(row['outcome'], search.INVALID_LOAD)
        self.assertEqual(result.search_status, 'stopped_invalid_load')
        self.assertEqual(self.terminal(), search.INVALID_LOAD)
        self.assertEqual(scorer.seen, [], 'nothing can turn a dead generator into a capacity result')
        self.assertEqual(len(result.runs), 1, 'the remaining runs stop')

    def test_the_swarms_own_criteria_verdict_is_not_a_generator_failure(self):
        # The real binary exits 1, with its report written, when the server misses its success criteria.
        self.guests.bot_exit = (1, None)
        score = self.scorer({25: search.FAIL, 5: search.FAIL})
        result = self.sim.executor(scorer=score).execute()
        self.assertEqual([r['outcome'] for r in result.runs], [search.FAIL, search.FAIL], 'a capacity failure stays available to the scorer')
        self.assertEqual(result.search_status, 'no_passing_target')
        self.assertIsNone(self.terminal())
        self.assertEqual(len(score.seen), 2)

    def test_that_verdict_alone_is_still_nothing_without_a_scorer(self):
        self.guests.bot_exit = (1, None)
        _, row = self.outcome_of_first_run(rf.scripted_scorer(default=None))
        self.assertEqual(row['outcome'], search.INCONCLUSIVE)

    def test_exit_one_without_a_report_is_required_evidence_missing(self):
        self.guests.bot_exit = (1, None)
        self.guests.no_report = True
        _, row = self.outcome_of_first_run()
        self.assertEqual(row['outcome'], search.INFRASTRUCTURE_FAILURE)
        self.assertTrue(any('report.json' in reason for reason in row['reasons']))

    def test_every_other_exit_status_is_a_generator_failure(self):
        for status in ((2, None), (101, None), (None, 9)):
            with self.subTest(status=status):
                self.setUp()
                self.guests.bot_exit = status
                score = self.scorer({25: search.FAIL})
                _, row = self.outcome_of_first_run(score)
                self.assertEqual(row['outcome'], search.INVALID_LOAD)
                self.assertEqual(score.seen, [])

    def test_both_failing_needs_the_server_named_as_the_cause(self):
        self.guests.bot_exit = (3, None)
        self.guests.game_crash_after_s = 10.0
        result, row = self.outcome_of_first_run(self.scorer({25: search.FAIL}))
        self.assertEqual(row['outcome'], search.INCONCLUSIVE)
        self.assertIn('a capacity failure with a failed generator needs the server named as the cause', row['reasons'])

    def test_a_swarm_that_overran_its_bound_is_inconclusive_not_capacity(self):
        self.guests.bot_hangs = True
        scorer = self.scorer({25: search.FAIL})
        result, row = self.outcome_of_first_run(scorer)
        self.assertEqual(row['outcome'], search.INCONCLUSIVE)
        self.assertEqual(scorer.seen, [])
        self.assertTrue(any('overran' in reason for reason in row['reasons']))

    def test_lost_contact_is_infrastructure(self):
        self.guests.bot_seconds = 500.0
        self.guests.unreachable.add(('bot', 'status'))
        result, row = self.outcome_of_first_run()
        self.assertEqual(row['outcome'], search.INFRASTRUCTURE_FAILURE)
        self.assertEqual(result.search_status, 'stopped_infrastructure_failure')

    def test_a_dead_sampler_stops_the_run_as_infrastructure(self):
        self.guests.sampler_dies_after_s['game'] = 15.0
        result, row = self.outcome_of_first_run()
        self.assertEqual(row['outcome'], search.INFRASTRUCTURE_FAILURE)
        self.assertTrue(any('sampler' in reason for reason in row['reasons']))

    def test_missing_required_evidence_stops_as_infrastructure(self):
        self.guests.no_report = True
        result, row = self.outcome_of_first_run()
        self.assertEqual(row['outcome'], search.INFRASTRUCTURE_FAILURE)
        self.assertTrue(any('report.json' in reason for reason in row['reasons']))

    def test_a_game_start_failure_is_infrastructure_with_nothing_launched_on_the_bot(self):
        self.guests.fail_start['game'] = 'launch_failed'
        result, row = self.outcome_of_first_run()
        self.assertEqual(row['outcome'], search.INFRASTRUCTURE_FAILURE)
        self.assertEqual(self.guests.runner_steps('bot', 'start'), [])

    def test_a_game_that_never_opens_its_socket_is_infrastructure(self):
        self.guests.socket_never_opens = True
        result, row = self.outcome_of_first_run()
        self.assertEqual(row['outcome'], search.INFRASTRUCTURE_FAILURE)
        self.assertEqual(self.guests.runner_steps('bot', 'start'), [])

    def test_a_bad_export_is_never_promoted(self):
        self.guests.corrupt_export.add('bot.stdout.log')
        result, row = self.outcome_of_first_run()
        self.assertEqual(row['outcome'], search.INFRASTRUCTURE_FAILURE)
        run_dir = self.sim.run_dir(row['run_id'])
        self.assertFalse((run_dir / 'bot' / 'bot.stdout.log').exists())
        self.assertTrue((run_dir / 'bot' / 'bot.stdout.log.partial').exists(), 'the failed bytes are retained, unpromoted')

    def test_old_process_identity_is_refused(self):
        executor = self.sim.executor(scorer=self.scorer({25: search.PASS}))
        original = self.guests._do_start
        host = self.guests.hosts['game']

        def replay_identity(run_host, argv):
            if run_host is host and host.ledger:
                old = next(e for e in host.ledger if 'processes' in e)
                host.scripted_identity = dict(old['processes']['game'])
            return original(run_host, argv)
        self.guests._do_start = replay_identity
        result = executor.execute()
        self.assertEqual(result.runs[-1]['outcome'], search.INFRASTRUCTURE_FAILURE)
        self.assertTrue(any('identity of an earlier process' in reason for reason in result.runs[-1]['reasons']))

    def test_old_socket_identity_is_refused(self):
        original = self.guests._do_start
        host = self.guests.hosts['game']

        def reuse_inode(run_host, argv):
            sealed = [e for e in host.ledger if e.get('sealed')]
            if run_host is host and sealed:
                host.scripted_inode = sealed[0]['socket_inodes'][0]
            return original(run_host, argv)
        self.guests._do_start = reuse_inode
        result = self.sim.executor(scorer=self.scorer({25: search.PASS})).execute()
        self.assertEqual(result.runs[-1]['outcome'], search.INFRASTRUCTURE_FAILURE)
        self.assertTrue(any('identity of an earlier run' in reason for reason in result.runs[-1]['reasons']))

    def test_a_counter_reset_during_a_run_is_refused(self):
        self.guests.drop_counter_rewind = True
        _, row = self.outcome_of_first_run()
        self.assertEqual(row['outcome'], search.INFRASTRUCTURE_FAILURE)
        self.assertIn('the game socket counter moved backward', row['reasons'])


class HostsNotReset(Base):
    """A dirty host stops the batch before dispatch, so the run stays untouched and nothing is claimed about it."""

    def assert_stopped_untouched(self, needle):
        result = self.sim.executor(scorer=self.scorer()).execute()
        self.assertEqual((result.status, result.code), (run_executor.STOPPED, 'host_not_reset'))
        self.assertIn(needle, result.detail)
        self.assertEqual(self.sim.records(), [], 'nothing was dispatched')
        self.assertEqual(self.guests.starts(), [])
        self.assertEqual(self.terminal(), search.INFRASTRUCTURE_FAILURE, 'the failure survives this controller')

    def test_leftover_socket(self):
        self.guests.hosts['game'].busy_ports.add(run_plan.GAME_PORT)
        self.assert_stopped_untouched('still holds a socket')

    def test_leftover_netem(self):
        self.guests.hosts['bot'].qdiscs.append('netem')
        self.assert_stopped_untouched('qdisc netem')

    def test_leftover_filter(self):
        self.guests.hosts['game'].filters = 2
        self.assert_stopped_untouched('filters remain')

    def test_leftover_process(self):
        self.guests.hosts['bot'].leftovers.append(dict(path='omega-load-test', pid=999))
        self.assert_stopped_untouched('processes remain')

    def test_leftover_unit(self):
        self.guests.hosts['game'].units.append('omega-run-old-game.service')
        self.assert_stopped_untouched('units remain')

    def test_changed_binary(self):
        self.guests.hosts['game'].file_overrides['/home/deploy/omega-release/omega-server'] = 'f' * 64
        self.assert_stopped_untouched('frozen hash')

    def test_changed_config(self):
        self.guests.hosts['game'].file_overrides['/home/deploy/omega-release/server_config.json'] = 'f' * 64
        self.assert_stopped_untouched('frozen hash')

    def test_changed_source_on_the_host(self):
        self.guests.hosts['bot'].source_head = '1' * 40
        self.assert_stopped_untouched('frozen clean revision')

    def test_rebooted_host(self):
        self.guests.hosts['game'].boot_id = 'another-boot'
        self.assert_stopped_untouched('boot identity changed')

    def test_an_active_run_blocks_the_next(self):
        self.guests.hosts['game'].active = dict(run_id='old', role='game')
        self.assert_stopped_untouched('another run is active')


class Deadlines(Base):
    def test_time_exhaustion_is_a_labelled_partial_search_not_a_result(self):
        status = self.sim.status_now()
        c = session_clock.parse(status['cleanup_c_utc'])
        self.sim.sleep(c - self.sim.clock.wall() - 1800)
        token = self.sim.client.acquire(self.sim.session_id, takeover=True)['fencing_token']
        executor = self.sim.executor(token=token, scorer=self.scorer())
        self.sim.client.mutate('record_resume', session_id=self.sim.session_id, fencing_token=token, operator_request_ref='fixture',
                               checks={**{n: True for n in registry.RESUME_REQUIRED_CHECKS}, 'manifest_sha256': self.sim.sha, 'next_run_id': search.next_trial(search.SearchState(self.sim.session_id)).run_id})
        result = executor.execute()
        self.assertEqual((result.status, result.search_status), (run_executor.PARTIAL, 'partial_time_exhausted'))
        self.assertEqual(self.sim.records(), [])
        self.assertIsNone(self.terminal())

    def test_a_stale_grant_is_not_used(self):
        executor = self.sim.executor(scorer=self.scorer())
        real_dispatch = executor._dispatch

        def slow_dispatch(trial, estimate):
            grant = real_dispatch(trial, estimate)
            self.sim.sleep(31)
            return grant
        executor._dispatch = slow_dispatch
        result = executor.execute()
        self.assertEqual(self.guests.starts(), [], 'a grant that sat too long launches nothing')
        self.assertEqual(result.runs[0]['outcome'], search.INCOMPLETE)
        self.assertEqual(result.search_status, 'undecidable_incomplete_predecessor')

    def test_a_start_that_reaches_the_guest_late_is_refused_there(self):
        executor = self.sim.executor(scorer=self.scorer())
        real = self.guests._run_runner

        def late(role, argv, timeout_s, on_wait):
            if argv[2] == 'start':
                self.sim.clock.advance(40)
            return real(role, argv, timeout_s, on_wait)
        self.guests._run_runner = late
        result = executor.execute()
        self.assertEqual(result.runs[0]['outcome'], search.INCOMPLETE)
        self.assertEqual(self.guests.hosts['game'].runs, {})

    def test_a_workload_that_hangs_is_ended_by_its_bound_with_time_left_for_export(self):
        self.guests.bot_hangs = True
        result = self.sim.executor(scorer=self.scorer()).execute()
        row = self.sim.records()[0]
        self.assertEqual(row['outcome'], search.INCONCLUSIVE)
        bot = self.guests.hosts['bot'].runs[row['run_id']]
        self.assertEqual(bot.stop_reason, 'bound_exhausted')
        self.assertLessEqual(session_clock.parse(row['finished_at']), session_clock.parse(row['must_stop_by']) + 1)

    def test_cleanup_during_a_run_stops_it_and_keeps_its_evidence(self):
        executor = self.sim.executor(scorer=self.scorer())
        real_watch = executor._watch

        def watch_then_abort(context):
            self.sim.stack.registry.operator_abort(self.sim.session_id, 'operator abort during a run')
            executor.next_renew = None
            real_watch(context)
        executor._watch = watch_then_abort
        result = executor.execute()
        self.assertEqual(result.status, run_executor.CLEANUP_STARTED)
        row = self.sim.records()[0]
        self.assertEqual(row['outcome'], search.INCOMPLETE)
        self.assertTrue(self.guests.hosts['game'].runs[row['run_id']].sealed)
        self.assertEqual(len(self.guests.starts()), 2)
        final = self.sim.drive_cleanup()
        self.assertEqual(final['cleanup']['outcome'], registry.VERIFIED_ABSENT)

    def test_the_watchdog_deletes_at_c_with_no_controller_left(self):
        executor = self.sim.executor(scorer=self.scorer(), failpoint=rf.crash_at('after_running_commit'))
        with self.assertRaises(rf.SimulatedCrash):
            executor.execute()
        final = self.sim.drive_cleanup(limit_s=20000)
        self.assertEqual(final['cleanup']['reason'], 'deadline_C')
        self.assertEqual(self.sim.session_droplets(), [])
        self.assertEqual(self.sim.records()[0]['state'], 'interrupted')

    def test_no_guest_command_starts_past_the_work_cutoff(self):
        executor = self.sim.executor(scorer=self.scorer())
        executor.prepare()
        c = session_clock.parse(self.sim.status_now()['cleanup_c_utc'])
        self.assertAlmostEqual(executor.work_cutoff - self.sim.monotonic(), c - registry.DELETE_MARGIN_S - self.sim.clock.wall(), delta=1)
        self.sim.clock.advance(c - self.sim.clock.wall())
        before = len(self.guests.calls)
        with self.assertRaises(run_executor.GuestLost):
            executor._runner('game', 'inspect')
        self.assertEqual(len(self.guests.calls), before)
        executor.in_recovery = True
        self.assertEqual(executor._guest_timeout(7), 7, 'recovery has its own deadline, up to C itself')

    def test_a_late_export_reports_failure_rather_than_passing_the_cutoff(self):
        executor = self.sim.executor(scorer=self.scorer())
        real_finish = executor._finish_run

        def at_cutoff(context):
            executor.work_cutoff = self.sim.monotonic()
            real_finish(context)
        executor._finish_run = at_cutoff
        result = executor.execute()
        self.assertEqual(result.runs[0]['outcome'], search.INFRASTRUCTURE_FAILURE)

    def test_process_reset_budget_that_cannot_hold_the_start_wait_is_refused(self):
        policy = run_executor.Policy(game_start_wait_s=100.0)
        result = self.sim.executor(scorer=self.scorer(), policy=policy).execute()
        self.assertEqual((result.status, result.code), (run_executor.REFUSED, 'timing_basis_too_small'))
        self.assertEqual(self.guests.starts(), [])


class CrashWindows(Base):
    """Die at each boundary, come back, and see what stayed true. Nothing is ever replayed or continued."""
    BEFORE_ANY_DISPATCH = ('after_selection', 'before_dispatch_commit')
    AFTER_DISPATCH_NOTHING_RUNNING = ('after_dispatch_commit', 'after_launching_commit')
    ACTIVE = ('after_game_start', 'after_bot_start', 'after_running_commit')

    def assert_no_duplicate_starts(self):
        for role in ('game', 'bot'):
            starts = self.guests.runner_steps(role, 'start')
            self.assertLessEqual(len(starts), len({*self.guests.hosts[role].runs}) + 0)

    def test_before_dispatch_the_trial_is_untouched_and_resume_runs_it_once(self):
        for point in self.BEFORE_ANY_DISPATCH:
            with self.subTest(point=point):
                self.setUp()
                self.crash_run(point)
                self.assertEqual(self.sim.records(), [])
                executor, outcome = self.resume()
                self.assertTrue(outcome['resumed'], outcome)
                self.assertEqual(outcome['next_run_id'], search.run_id(self.sim.session_id, 1, search.COARSE, 25, 1))
                result = executor.execute()
                self.assertEqual(result.search_status, 'confirmed')
                self.assertEqual(self.sim.records()[0]['outcome'], search.PASS)
                self.assert_no_duplicate_starts()

    def test_after_dispatch_a_first_rung_is_lost_to_this_batch_and_the_dependent_path_stops(self):
        for point in self.AFTER_DISPATCH_NOTHING_RUNNING + self.ACTIVE:
            with self.subTest(point=point):
                self.setUp()
                self.crash_run(point)
                self.assertEqual(self.sim.status_now()['state'], registry.RUNNING)
                executor, outcome = self.resume()
                self.assertFalse(outcome['resumed'])
                self.assertEqual(outcome['code'], 'no_eligible_untouched_work')
                self.assertIn('undecidable_incomplete_predecessor', outcome['detail'])
                self.assertEqual(self.sim.records()[0]['outcome'], search.INCOMPLETE)
                self.assertEqual(self.state(), registry.PAUSED)
                self.assert_no_duplicate_starts()
                self.assertEqual(len(self.sim.records()), 1, 'never replayed')
                for host in self.guests.hosts.values():
                    for run in host.runs.values():
                        self.assertFalse(self.guests._alive(run), 'nothing keeps running')
                        self.assertIsNotNone(run.sealed, 'interrupted evidence is preserved')
                        self.assertEqual(run.sealed['interrupted'], 'controller_replaced')

    def test_an_interrupted_active_run_keeps_its_directory_and_is_never_replayed(self):
        self.crash_run('after_running_commit')
        run_id = self.sim.records()[0]['run_id']
        first_identity = dict(self.guests.hosts['game'].runs[run_id].identity['processes']['game'])
        self.resume()
        self.assertEqual(self.guests.hosts['game'].runs[run_id].identity['processes']['game'], first_identity, 'not restarted')
        self.assertEqual(len(self.guests.runner_steps('game', 'start')), 1)
        self.assertTrue((self.sim.run_dir(run_id) / 'game' / guest_runner.SEAL).exists())
        self.assertTrue((self.sim.run_dir(run_id) / 'bot' / guest_runner.SEAL).exists())

    def test_a_crash_after_seal_with_proof_of_a_natural_end_scores_from_retained_evidence(self):
        scorer = self.scorer()
        self.crash_run('after_seal', scorer=scorer)
        executor, outcome = self.resume(scorer=scorer)
        row = self.sim.records()[0]
        self.assertEqual(row['outcome'], search.PASS, 'the evidence itself proves the workload finished')
        self.assertTrue(outcome['resumed'], outcome)
        self.assertEqual(outcome['next_run_id'], search.run_id(self.sim.session_id, 2, search.COARSE, 50, 1))
        self.assertEqual(len(self.guests.runner_steps('game', 'start')), 1)

    def test_crashes_between_the_natural_end_and_the_verdict_score_only_once_from_what_was_left(self):
        for point in ('after_stop', 'after_execution_record'):
            with self.subTest(point=point):
                self.setUp()
                scorer = self.scorer()
                self.crash_run(point, scorer=scorer)
                self.assertEqual(scorer.seen, [])
                run_id = self.sim.records()[0]['run_id']
                _, outcome = self.resume(scorer=scorer)
                self.assertEqual(self.sim.records()[0]['outcome'], search.PASS)
                self.assertEqual(len(scorer.seen), 1)
                self.assertTrue(outcome['resumed'], outcome)
                self.assertEqual(len(self.guests.runner_steps('game', 'start')), 1)
                self.assertTrue((self.sim.run_dir(run_id) / 'execution.json').exists(), 'the earlier record, if any, is kept')

    def test_natural_end_with_no_scorer_stays_incomplete(self):
        self.crash_run('after_seal')
        executor, control = self.sim.controller(scorer=None)
        outcome = executor.resume('op', control)
        self.assertEqual(self.sim.records()[0]['outcome'], search.INCOMPLETE)
        self.assertEqual(outcome['code'], 'no_eligible_untouched_work')

    def test_a_crash_just_before_the_outcome_commit_keeps_the_verdict_already_reached(self):
        self.crash_run('before_outcome_commit')
        self.assertIsNone(self.sim.records()[0]['outcome'])
        scorer = self.scorer({25: search.FAIL})    # a second opinion must not replace the first
        executor, outcome = self.resume(scorer=scorer)
        self.assertEqual(self.sim.records()[0]['outcome'], search.PASS)
        self.assertEqual(scorer.seen, [], 'not scored twice')
        self.assertTrue(outcome['resumed'])

    def test_a_terminal_verdict_cannot_be_escaped_by_crashing_before_its_commit(self):
        self.guests.bot_exit = (77, None)
        self.crash_run('before_outcome_commit')
        executor, outcome = self.resume()
        self.assertEqual(self.sim.records()[0]['outcome'], search.INVALID_LOAD)
        self.assertFalse(outcome['resumed'])
        self.assertEqual(outcome['code'], 'terminal_failure')

    def test_a_crash_after_the_outcome_commit_repairs_the_journal_without_a_second_outcome(self):
        self.crash_run('after_outcome_commit')
        row = self.sim.records()[0]
        self.assertEqual(row['outcome'], search.PASS)
        path = self.sim.stack.root / 'search_journal.ndjson'
        self.assertNotIn('"kind":"outcome"', path.read_text().replace(' ', ''))
        executor, outcome = self.resume()
        self.assertTrue(outcome['resumed'], outcome)
        entries = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(len([e for e in entries if e['kind'] == 'outcome']), 1)
        result = executor.execute()
        self.assertEqual(result.search_status, 'confirmed')
        kept = [e['run_id'] for e in (json.loads(line) for line in path.read_text().splitlines()) if e['kind'] == 'outcome']
        self.assertEqual(len(kept), len(set(kept)))

    def test_a_crash_after_the_mirror_needs_nothing_repaired(self):
        self.crash_run('after_journal_mirror')
        executor, outcome = self.resume()
        self.assertTrue(outcome['resumed'], outcome)
        self.assertEqual(executor.execute().search_status, 'confirmed')

    def test_crash_between_runs_resumes_only_the_next_untouched_trial(self):
        # The first run finishes; the controller dies while preparing the second.
        executor = self.sim.executor(scorer=self.scorer())
        count = dict(n=0)

        def second_selection(name):
            if name == 'after_selection':
                count['n'] += 1
                if count['n'] == 2:
                    raise rf.SimulatedCrash(name)
        executor.failpoint = second_selection
        with self.assertRaises(rf.SimulatedCrash):
            executor.execute()
        self.assertEqual(len(self.sim.records()), 1)
        resumed, outcome = self.resume()
        self.assertTrue(outcome['resumed'], outcome)
        self.assertEqual(outcome['next_run_id'], search.run_id(self.sim.session_id, 2, search.COARSE, 50, 1))
        result = resumed.execute()
        self.assertEqual(result.search_status, 'confirmed')
        self.assertEqual(len(self.guests.runner_steps('game', 'start')), len(self.sim.records()))

    def test_dispatch_acknowledgement_lost_is_one_run(self):
        calls = dict(n=0)
        original = self.sim.client.transport

        def lose_first_answer(request):
            response = original(request)
            if request['method'] == 'dispatch_run' and calls['n'] == 0:
                calls['n'] += 1
                raise registry_client.TransportError('answer lost')
            return response
        self.sim.client.transport = lose_first_answer
        result = self.sim.executor(scorer=self.scorer()).execute()
        self.sim.client.transport = original
        self.assertEqual(result.search_status, 'confirmed')
        self.assertEqual(len(self.guests.runner_steps('game', 'start')), len(self.sim.records()))

    def test_outcome_acknowledgement_lost_is_one_outcome(self):
        calls = dict(n=0)
        original = self.sim.client.transport

        def lose_first_answer(request):
            response = original(request)
            if request['method'] == 'record_run_outcome' and calls['n'] == 0:
                calls['n'] += 1
                raise registry_client.TransportError('answer lost')
            return response
        self.sim.client.transport = lose_first_answer
        result = self.sim.executor(scorer=self.scorer()).execute()
        self.sim.client.transport = original
        self.assertEqual(result.search_status, 'confirmed')
        self.assertEqual(len([e for e in self.sim.stack.registry.journal(self.sim.session_id) if e['kind'] == 'run_outcome']), len(result.runs))


class ConfirmationSiblings(Base):
    def test_an_incomplete_confirmation_leaves_its_untouched_siblings_eligible_but_never_confirms(self):
        scorer = self.scorer({25: search.PASS, 50: search.FAIL, 30: search.FAIL})
        executor = self.sim.executor(scorer=scorer)
        count = dict(n=0)

        def in_confirmation(name):
            if name == 'after_running_commit':
                count['n'] += 1
                if count['n'] == 4:     # coarse 25, coarse 50, refine 30, then the first confirmation
                    raise rf.SimulatedCrash(name)
        executor.failpoint = in_confirmation
        with self.assertRaises(rf.SimulatedCrash):
            executor.execute()
        resumed, outcome = self.resume(scorer=scorer)
        self.assertTrue(outcome['resumed'], outcome)
        self.assertIn('-confirm-n025-r2', outcome['next_run_id'])
        result = resumed.execute()
        self.assertEqual(result.search_status, 'unconfirmed_partial')
        self.assertEqual([r['outcome'] for r in self.sim.records() if '-confirm-' in r['run_id']], [search.INCOMPLETE, search.PASS, search.PASS])
        self.assertEqual(len(self.guests.runner_steps('game', 'start')), len(self.sim.records()), 'the incomplete confirmation was not replayed')


class ResumeRules(Base):
    """Each refusal in the lifecycle contract, against a pair that is otherwise eligible: a crash between runs."""

    def setUp(self):
        super().setUp()
        executor = self.sim.executor(scorer=self.scorer())
        count = dict(n=0)

        def second_selection(name):
            if name == 'after_selection':
                count['n'] += 1
                if count['n'] == 2:
                    raise rf.SimulatedCrash(name)
        executor.failpoint = second_selection
        with self.assertRaises(rf.SimulatedCrash):
            executor.execute()

    def assert_refused(self, code, **options):
        executor, outcome = self.resume(**options)
        self.assertFalse(outcome['resumed'], outcome)
        self.assertEqual(outcome['code'], code, outcome)
        self.assertEqual(len(self.sim.records()), 1, 'nothing new was dispatched')
        return outcome

    def test_the_eligible_case_resumes_after_recording_every_check(self):
        executor, outcome = self.resume()
        self.assertTrue(outcome['resumed'], outcome)
        for name in registry.RESUME_REQUIRED_CHECKS:
            self.assertIs(outcome['checks'][name], True, name)
        journal = [e for e in self.sim.stack.registry.journal(self.sim.session_id) if e['kind'] == 'resumed']
        self.assertEqual(journal[0]['data']['operator_request_ref'], 'operator: resume remaining runs')
        self.assertEqual(self.state(), registry.READY)
        history = (self.sim.stack.root / 'execution' / 'journal.ndjson').read_text()
        self.assertIn('resume_request', history)

    def test_returning_without_an_explicit_resume_dispatches_nothing(self):
        executor, _ = self.come_back()
        result = executor.execute()
        self.assertEqual(result.code, 'bad_state')
        self.assertEqual(len(self.sim.records()), 1)
        self.assertEqual(self.state(), registry.PAUSED)

    def test_a_terminal_infrastructure_failure_refuses(self):
        self.sim.client.mutate('record_batch_stop', session_id=self.sim.session_id, outcome=search.INFRASTRUCTURE_FAILURE, fencing_token=self.sim.result.fencing_token, detail='host failed')
        self.assert_refused('terminal_failure')

    def test_invalid_load_refuses(self):
        self.sim.client.mutate('record_batch_stop', session_id=self.sim.session_id, outcome=search.INVALID_LOAD, fencing_token=self.sim.result.fencing_token, detail='generator failed')
        self.assert_refused('terminal_failure')

    def test_an_operator_abort_refuses_and_cleanup_proceeds(self):
        self.sim.stack.registry.operator_abort(self.sim.session_id, 'operator changed their mind')
        self.assert_refused('cleanup_in_progress')
        self.assertEqual(self.sim.drive_cleanup()['cleanup']['outcome'], registry.VERIFIED_ABSENT)

    def test_a_cleanup_request_refuses(self):
        self.sim.client.mutate('request_cleanup', session_id=self.sim.session_id, fencing_token=self.sim.result.fencing_token, reason='batch finished')
        self.assert_refused('cleanup_in_progress')

    def test_c_refuses_and_the_deadline_does_not_move(self):
        before = self.sim.status_now()
        c = session_clock.parse(before['cleanup_c_utc'])
        self.sim.sleep(c - self.sim.clock.wall() + 1)
        self.assert_refused('cleanup_in_progress')
        after = self.sim.status_now()
        self.assertEqual((before['t0_utc'], before['cleanup_c_utc'], before['deadline_d_utc']), (after['t0_utc'], after['cleanup_c_utc'], after['deadline_d_utc']))

    def test_exhausted_original_headroom_refuses(self):
        c = session_clock.parse(self.sim.status_now()['cleanup_c_utc'])
        self.sim.sleep(c - self.sim.clock.wall() - 1500)
        outcome = self.assert_refused('headroom_exhausted')
        self.assertIn('maximal legal remaining path', outcome['detail'])

    def test_a_live_lease_needs_explicit_takeover(self):
        client = rf.pf.client_for(self.sim, 'controller-c')
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            client.acquire(self.sim.session_id, takeover=False)
        self.assertEqual(caught.exception.code, 'control_held')

    def test_changed_controller_source_refuses(self):
        self.assert_refused('source_changed', source_problems=lambda: ['the controller checkout is not the frozen controller revision'])

    def test_changed_source_on_the_host_refuses(self):
        self.guests.hosts['bot'].source_head = '1' * 40
        self.assert_refused('host_not_reset')

    def test_a_changed_program_refuses(self):
        self.guests.hosts['bot'].file_overrides['/home/deploy/omega-release/omega-load-test'] = 'f' * 64
        self.assert_refused('host_not_reset')

    def test_a_replaced_host_refuses(self):
        droplet = self.sim.account.droplets[int(self.sim.result.droplets['game'])]
        droplet['networks']['v4'][0]['ip_address'] = '198.51.100.222'
        outcome = self.assert_refused('pair_changed')
        self.assertIn('moved', outcome['detail'])

    def test_a_resized_host_refuses(self):
        droplet = self.sim.account.droplets[int(self.sim.result.droplets['game'])]
        droplet['size_slug'] = 's-2vcpu-2gb-amd'
        droplet['size'] = dict(droplet['size'], slug='s-2vcpu-2gb-amd') if isinstance(droplet.get('size'), dict) else droplet.get('size')
        self.assert_refused('pair_changed')

    def test_a_deleted_host_refuses(self):
        del self.sim.account.droplets[int(self.sim.result.droplets['bot'])]
        self.assert_refused('pair_changed')

    def test_a_retargeted_firewall_refuses_and_opens_an_incident(self):
        firewall = self.sim.account.firewalls[self.sim.result.firewall_id]
        firewall['tags'] = ['production']
        self.assert_refused('pair_changed')
        self.assertTrue(self.sim.open_incidents())

    def test_a_widened_firewall_refuses(self):
        firewall = self.sim.account.firewalls[self.sim.result.firewall_id]
        firewall['inbound_rules'][0]['sources']['addresses'] = ['0.0.0.0/0']
        self.assert_refused('pair_changed')

    def test_a_rebooted_host_fails_readiness(self):
        real_probe = self.guests._answer_probe

        def rebooted(role):
            return dict(real_probe(role), clock=dict(real_probe(role)['clock'], boot_id='another-boot'))
        self.guests._answer_probe = rebooted
        outcome = self.assert_refused('readiness_failed')
        self.assertIn('rebooted', outcome['detail'])

    def test_changed_packages_fail_readiness(self):
        self.guests.package_versions['game'] = dict(libc6='9.9-changed')
        outcome = self.assert_refused('readiness_failed')
        self.assertIn('package inventory changed', outcome['detail'])

    def test_a_failed_smoke_fails_readiness(self):
        self.guests.break_step('bot', 'smoke_bot', connected_bots=0)
        self.assert_refused('readiness_failed')

    def test_leftover_netem_refuses(self):
        self.guests.hosts['game'].qdiscs.append('netem')
        outcome = self.assert_refused('host_not_reset')
        self.assertIn('netem', outcome['detail'])

    def test_a_changed_readiness_record_refuses(self):
        path = self.sim.stack.root / 'provisioning' / 'readiness.json'
        path.write_text(path.read_text() + ' ')
        self.assert_refused('readiness_record_changed')

    def test_a_changed_manifest_refuses(self):
        executor, control = self.come_back()
        executor.sha = '0' * 64
        outcome = executor.resume('op', control)
        self.assertFalse(outcome['resumed'])
        self.assertEqual(outcome['code'], 'manifest_changed')

    def test_an_unreachable_host_refuses_with_no_claim(self):
        self.guests.unreachable.add(('bot', 'fence'))
        outcome = self.assert_refused('GuestLost')

    def test_a_refused_resume_can_still_collect_and_delete(self):
        import run_cli
        self.guests.hosts['game'].qdiscs.append('netem')
        self.assert_refused('host_not_reset')
        client = rf.pf.client_for(self.sim, 'controller-d')
        result, problems = run_cli.collect_and_stop(client, self.sim.session_id, lambda token: self.sim.executor(client=client, token=token, scorer=self.scorer()), 'resume was refused', takeover=True)
        self.assertEqual(result.code, 'operator_collect')
        final = self.sim.drive_cleanup()
        self.assertEqual(final['cleanup']['outcome'], registry.VERIFIED_ABSENT)
        self.assertEqual(final['measurement']['outcome'], 'operator_collect')


class Fencing(Base):
    def test_a_stale_controller_is_refused_by_the_registry_and_the_host(self):
        stale = self.sim.executor(scorer=self.scorer(), failpoint=rf.crash_at('after_launching_commit'))
        with self.assertRaises(rf.SimulatedCrash):
            stale.execute()
        new, control = self.sim.controller(scorer=self.scorer())
        new.prepare()   # raises the fence on both hosts
        trial = search.trial_from_dict(self.sim.records()[0]['trial'])
        plan = stale._plan(trial, 'game', self.sim.clock.wall() + 30, 100.0, self.sim.clock.wall() + 200)
        document = None
        with self.assertRaises(run_executor.ControlLost) as caught:
            document = stale._runner('game', 'start', '--plan-json', json.dumps(plan))
        self.assertEqual(caught.exception.code, 'stale_fence')
        self.assertIsNone(document)
        self.assertEqual(self.guests.hosts['game'].runs, {})

    def test_takeover_mid_run_stops_the_old_controller_and_the_new_one_owns_the_rest(self):
        old = self.sim.executor(scorer=self.scorer())
        real_watch = old._watch
        taken = {}

        def taken_over(context):
            taken['executor'], taken['control'] = self.sim.controller(scorer=self.scorer())
            old.next_renew = None
            real_watch(context)
        old._watch = taken_over
        result = old.execute()
        self.assertEqual(result.status, run_executor.CONTROL_LOST)
        self.assertEqual(result.code, 'stale_fencing_token')
        row = self.sim.records()[0]
        self.assertIsNone(row['outcome'], 'a stale controller records nothing')
        outcome = taken['executor'].resume('operator', taken['control'])
        self.assertEqual(self.sim.records()[0]['outcome'], search.INCOMPLETE)
        self.assertEqual(outcome['code'], 'no_eligible_untouched_work')

    def test_a_stale_controller_cannot_commit_an_outcome(self):
        stale = self.sim.executor(scorer=self.scorer(), failpoint=rf.crash_at('before_outcome_commit'))
        with self.assertRaises(rf.SimulatedCrash):
            stale.execute()
        self.sim.controller(scorer=self.scorer())
        with self.assertRaises(run_executor.ControlLost):
            stale._record_outcome(self.sim.records()[0]['run_id'], search.PASS, 'runs/x')

    def test_a_lost_registry_during_a_run_ends_as_control_lost_once_the_lease_cannot_be_proved(self):
        executor = self.sim.executor(scorer=self.scorer())
        original = self.sim.client.transport
        real_watch = executor._watch

        def registry_gone(context):
            def refuse(request):
                raise registry_client.TransportError('registry unreachable')
            self.sim.client.transport = refuse
            executor.next_renew = None
            self.guests.bot_seconds = 10000.0
            real_watch(context)
        executor._watch = registry_gone
        result = executor.execute()
        self.sim.client.transport = original
        self.assertEqual(result.status, run_executor.CONTROL_LOST)
        self.assertEqual(result.code, 'lease_unverifiable')
        run = next(iter(self.guests.hosts['bot'].runs.values()))
        self.assertFalse(self.guests._alive(run), 'the workload was stopped on the way out')


class ControllerSource(unittest.TestCase):
    class Done:
        def __init__(self, code=0, out=b''):
            self.returncode, self.stdout = code, out

    MANIFEST = dict(source=dict(controller_sha='abc123'))

    def check(self, head=b'abc123\n', dirty=b''):
        answers = iter([self.Done(0, head), self.Done(0, dirty)])
        return run_executor.source_identity_problems(self.MANIFEST, '/repo', runner=lambda argv: next(answers))

    def test_exact_clean_checkout_passes(self):
        self.assertEqual(self.check(), [])

    def test_another_revision_or_edits_fail(self):
        self.assertIn('the controller checkout is not the frozen controller revision', self.check(head=b'def456\n'))
        self.assertIn('the controller code has uncommitted changes', self.check(dirty=b' M scripts/do_session/run_executor.py\n'))


class ScorerBoundary(unittest.TestCase):
    SCORABLE = dict(scorable=True, outcome=None, reasons=[], generator_failed=False, game_failed=False)

    def test_refusals_never_become_a_pass(self):
        cases = [(None, 'no reviewed scorer'), (dict(outcome='MAYBE', evidence_ref='x'), 'unknown outcome'), (dict(outcome='PASS'), 'named no evidence'), ('PASS', 'unknown outcome')]
        for answer, text in cases:
            verdict = run_checks.apply_scorer(self.SCORABLE, answer)
            self.assertEqual(verdict['outcome'], search.INCONCLUSIVE, answer)
            self.assertIn(text, verdict['reasons'][0])

    def test_settled_facts_ignore_the_scorer(self):
        settled = dict(scorable=False, outcome=search.INVALID_LOAD, reasons=['swarm crashed'])
        self.assertEqual(run_checks.apply_scorer(settled, dict(outcome=search.PASS, evidence_ref='x'))['outcome'], search.INVALID_LOAD)

    def test_a_scored_answer_keeps_its_evidence(self):
        verdict = run_checks.apply_scorer(self.SCORABLE, dict(outcome=search.PASS, evidence_ref='runs/x', scorer='s'))
        self.assertEqual((verdict['outcome'], verdict['evidence_ref'], verdict['scored']), (search.PASS, 'runs/x', True))


class PinRestoration(unittest.TestCase):
    def test_a_later_controller_only_inherits_pins(self):
        import pathlib
        import tempfile
        import os
        import ssh_access
        with tempfile.TemporaryDirectory() as root:
            key = pathlib.Path(root) / 'key'
            key.write_text('synthetic')
            os.chmod(str(key), 0o600)
            access = ssh_access.SshAccess(key, root)
            (pathlib.Path(root) / 'known_hosts').write_text('198.51.100.10 ssh-ed25519 AAAA\n')
            access.restore_pins(dict(game='198.51.100.10'))
            self.assertEqual(access.pins['game'], '198.51.100.10')
            with self.assertRaises(ssh_access.HostVerificationFailed):
                access.restore_pins(dict(bot='198.51.100.99'))


if __name__ == '__main__':
    unittest.main()
