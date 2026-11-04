"""The real guest runner as real processes on this machine: fences, identity, bounds, sockets and sealing.

Stand-in workloads hold real sockets and take real signals. What cannot run here is named where it is faked: ``tc`` is a
scripted program, and the systemd path runs through shims. Neither says anything about a real Droplet.
"""
import json
import os
import pathlib
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import fake_run_guest
import guest_runner
import run_checks
import run_executor
import run_fixtures as rf
import run_plan
import search

SESSION = 'do-local-guest-a'
HERE = pathlib.Path(__file__).parent
PROC_NET_UDP = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode ref pointer drops
  611: 00000000:1F91 00000000:0000 07 00000000:00000200 00:00000000 00000000  1000        0 91234 2 ffff8e0 7
  612: 0100007F:1F92 00000000:0000 07 00000000:00000000 00:00000000 00000000  1000        0 91235 2 ffff8e1 0
"""


def wait_until(predicate, limit_s=10.0):
    deadline = time.monotonic() + limit_s
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError('the condition was not reached')


class GuestFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.addCleanup(rf.make_writable, temporary.name)
        self.root = pathlib.Path(temporary.name)
        self.game_port, self.metrics_port = rf.free_ports()
        self.hosts = rf.install_local_hosts(self.root, self.game_port, self.metrics_port, workload_seconds=0.3)
        self.guests = self.hosts.guests
        self.adapter = self.hosts.adapter
        self.sha = run_executor.sha256_path(run_executor.RUNNER_SOURCE)
        self.runner = run_plan.runner_remote_path(self.sha)
        for role in ('game', 'bot'):
            self.guests.put(role, str(run_executor.RUNNER_SOURCE), self.runner, 5)
        programs = self.adapter.program_paths()
        self.manifest = dict(session=dict(id=SESSION), workload={}, source=dict(benchmark_sha='a' * 40, server_config_sha256=run_executor.sha256_path(self.adapter.config_path()),
                                                                                binary_sha256=dict(game=run_executor.sha256_path(programs['game']), bot=run_executor.sha256_path(programs['bot']))))
        self.sampler_sha = run_executor.sha256_path(self.adapter.sampler_path('game'))
        self.addCleanup(self.kill_all)

    def kill_all(self):
        for line in guest_runner.process_table() or ():
            if str(self.root) in line and line.split()[0].isdigit() and int(line.split()[0]) != os.getpid():
                try:
                    os.kill(int(line.split()[0]), signal.SIGKILL)
                except OSError:
                    pass

    def do(self, role, command, *arguments):
        result = self.guests.run(role, ['python3', self.runner, command] + list(arguments), 30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def trial(self, ordinal=1, target=25):
        return search.Trial(search.run_id(SESSION, ordinal, search.COARSE, target, 1), ordinal, search.COARSE, target, 1, search.EXPLORATION_HOLD_S, ())

    def plan(self, role='game', trial=None, token=1, bound_s=30.0, stop_grace_s=1.0, unit_mode=guest_runner.PROCESS_GROUP, launch_slack_s=60.0, stop_slack_s=600.0):
        return run_plan.role_plan(self.adapter, self.manifest, 'b' * 64, trial or self.trial(), role, dict(game='127.0.0.1', bot='127.0.0.1'), self.sampler_sha, token, unit_mode,
                                  time.time() + launch_slack_s, bound_s, time.time() + stop_slack_s, stop_grace_s)

    def fence(self, role='game', token=1):
        return self.do(role, 'fence', '--session', SESSION, '--token', str(token))

    def start(self, plan):
        return self.do(plan['role'], 'start', '--plan-json', json.dumps(plan))

    def status(self, plan):
        return self.do(plan['role'], 'status', '--run-id', plan['run_id'], '--role', plan['role'])

    def stop(self, plan, token=1, reason='test', wait_s=5.0):
        return self.do(plan['role'], 'stop', '--run-id', plan['run_id'], '--role', plan['role'], '--token', str(token), '--reason', reason, '--wait-s', str(wait_s))

    def seal(self, plan, token=1, *extra):
        return self.do(plan['role'], 'seal', '--run-id', plan['run_id'], '--role', plan['role'], '--token', str(token), *extra)

    def tree(self, plan):
        return self.guests.runner_root(plan['role']) / 'runs' / plan['run_id'] / plan['role']


class Fencing(GuestFixture):
    def test_the_fence_only_rises_and_a_replaced_controller_cannot_start_anything(self):
        self.assertTrue(self.fence(token=3)['raised'])
        self.assertFalse(self.fence(token=3)['raised'])
        lower = self.fence(token=2)
        self.assertEqual((lower['ok'], lower['code']), (False, 'stale_fence'))
        refused = self.start(self.plan(token=2))
        self.assertEqual(refused['code'], 'stale_fence')
        self.assertFalse(self.tree(self.plan(token=2)).exists(), 'a refused start leaves no directory')

    def test_a_start_with_no_fence_is_refused(self):
        self.assertEqual(self.start(self.plan())['code'], 'not_fenced')

    def test_another_session_cannot_fence_this_host(self):
        self.fence()
        document = self.do('game', 'fence', '--session', 'other-session', '--token', '9')
        self.assertEqual(document['code'], 'foreign_session')

    def test_a_stale_controller_cannot_stop_or_seal_a_newer_run(self):
        self.fence()
        plan = self.plan()
        self.assertTrue(self.start(plan)['ok'])
        self.fence(token=2)
        self.assertEqual(self.stop(plan, token=1)['code'], 'stale_fence')
        self.assertEqual(self.seal(plan, 1)['code'], 'stale_fence')
        self.assertTrue(self.status(plan)['supervisor']['alive'])
        self.assertTrue(self.stop(plan, token=2)['stopped'])


class Launch(GuestFixture):
    def test_a_run_gets_fresh_identities_a_private_tree_and_an_independent_sampler(self):
        self.fence()
        first_plan = self.plan()
        first = self.start(first_plan)
        self.assertTrue(first['ok'], first)
        wait_until(lambda: self.status(first_plan)['socket'])
        self.stop(first_plan)
        self.seal(first_plan)
        second_plan = self.plan(trial=self.trial(2, 50))
        second = self.start(second_plan)
        self.assertTrue(second['ok'], second)
        wait_until(lambda: self.status(second_plan)['socket'])
        self.assertNotEqual(first['processes']['game']['pid'], second['processes']['game']['pid'])
        self.assertNotEqual(first['processes']['sampler']['pid'], second['processes']['sampler']['pid'])
        self.assertNotEqual(first['processes']['game']['pid'], first['processes']['sampler']['pid'], 'the sampler is its own process')
        self.assertNotEqual(self.tree(first_plan), self.tree(second_plan))
        ledger = self.do('game', 'inspect')['ledger']
        self.assertEqual(run_checks.launch_problems(second_plan, second, [e for e in ledger if e['run_id'] != second_plan['run_id']]), [])
        self.assertEqual(run_checks.socket_problems(second_plan, self.status(second_plan), [e for e in ledger if e['run_id'] != second_plan['run_id']], False), [])

    def test_a_second_start_while_one_is_active_is_an_overlap(self):
        self.fence()
        self.start(self.plan())
        self.assertEqual(self.start(self.plan(trial=self.trial(2, 50)))['code'], 'overlap')

    def test_the_same_run_id_can_never_start_again(self):
        self.fence()
        plan = self.plan()
        self.start(plan)
        self.stop(plan)
        self.seal(plan)
        before = run_executor.sha256_path(self.tree(plan) / guest_runner.SEAL)
        self.assertEqual(self.start(plan)['code'], 'duplicate_run_dir')
        self.assertEqual(run_executor.sha256_path(self.tree(plan) / guest_runner.SEAL), before, 'nothing was overwritten')

    def test_a_plan_cannot_name_a_path_outside_its_run_tree(self):
        self.fence()
        for changes in (dict(role='../../escape'), dict(run_id='../escape'), dict(schema='other')):
            document = self.do('game', 'start', '--plan-json', json.dumps(dict(self.plan(), **changes)))
            self.assertEqual(document['code'], 'bad_request', changes)
        self.assertFalse((self.guests.runner_root('game') / 'escape').exists())

    def test_a_late_start_request_is_refused_on_the_guest(self):
        self.fence()
        self.assertEqual(self.start(self.plan(launch_slack_s=-5.0))['code'], 'launch_window_closed')

    def test_changed_program_or_config_bytes_are_refused_immediately_before_launch(self):
        self.fence()
        plan = self.plan()
        pathlib.Path(self.adapter.config_path()).write_text('{"changed": true}\n')
        document = self.start(plan)
        self.assertEqual(document['code'], 'hash_mismatch')
        self.assertIn('server_config.json', document['detail'])

    def test_a_leftover_process_refuses_the_start_and_the_preflight_names_it(self):
        self.fence()
        program = self.adapter.program_paths()['game']
        leftover = subprocess.Popen([program, '--port', str(rf.free_ports(1)[0])], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (leftover.kill(), leftover.wait()))
        plan = self.plan()
        facts = wait_until(lambda: (lambda f: f if f['leftovers'] else None)(self.do('game', 'preflight', '--plan-json', json.dumps(plan))))
        self.assertEqual([item['pid'] for item in facts['leftovers']], [leftover.pid])
        self.assertEqual(self.start(plan)['code'], 'leftover_process')

    def test_a_held_port_refuses_the_start(self):
        self.fence()
        plan = self.plan()
        held = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        held.bind(('127.0.0.1', self.game_port))
        self.addCleanup(held.close)
        self.assertEqual(self.start(plan)['code'], 'port_busy')
        facts = self.do('game', 'preflight', '--plan-json', json.dumps(plan))
        self.assertIn('port udp/%d still holds a socket' % self.game_port, run_checks.host_problems(plan, facts, facts['boot_id'], facts['runner_sha256']))

    def test_the_plan_text_on_the_command_line_is_not_mistaken_for_a_leftover(self):
        self.fence()
        plan = self.plan()
        facts = self.do('game', 'preflight', '--plan-json', json.dumps(plan))
        self.assertEqual(facts['leftovers'], [])

    def test_uncleared_impairment_reaches_the_rules_from_a_real_subprocess(self):
        plan = self.plan()
        self.fence()
        self.hosts.state_file.write_text(json.dumps([dict(kind='prio', dev='lo0'), dict(kind='netem', dev='lo0')]))
        facts = self.do('game', 'preflight', '--plan-json', json.dumps(plan))
        problems = run_checks.host_problems(plan, facts, facts['boot_id'], facts['runner_sha256'])
        self.assertIn('qdisc netem is not a cleared state', problems)
        self.assertIn('qdisc prio is not a cleared state', problems)

    def test_missing_tc_is_unknown_not_clear(self):
        self.assertEqual(run_checks.impairment_problems(dict(available=False)), ['network impairment state could not be read'])
        self.assertEqual(run_checks.impairment_problems(None), ['network impairment state could not be read'])


class Bounds(GuestFixture):
    def test_a_workload_that_ignores_sigterm_still_ends_at_its_bound_with_no_controller(self):
        self.adapter.game_extra = ['--ignore-term']
        self.fence()
        plan = self.plan(bound_s=1.0, stop_grace_s=0.5)
        started = time.monotonic()
        self.assertTrue(self.start(plan)['ok'])
        final = wait_until(lambda: (lambda s: s if s['result'] else None)(self.status(plan)), 10.0)
        self.assertLess(time.monotonic() - started, 6.0)
        self.assertEqual(final['result']['stop_reason'], 'bound_exhausted')
        self.assertEqual(final['result']['processes']['game']['signal'], signal.SIGKILL)
        self.assertFalse(final['processes']['game']['alive'])

    def test_the_absolute_stop_time_holds_even_if_the_relative_bound_is_longer(self):
        self.fence()
        plan = self.plan(bound_s=60.0, stop_grace_s=0.2, stop_slack_s=0.8)
        self.assertTrue(self.start(plan)['ok'])
        final = wait_until(lambda: (lambda s: s if s['result'] else None)(self.status(plan)), 10.0)
        self.assertEqual(final['result']['stop_reason'], 'bound_exhausted')

    def test_a_dead_supervisor_cannot_leave_a_workload_running(self):
        self.fence()
        plan = self.plan()
        started = self.start(plan)
        os.kill(started['supervisor']['pid'], signal.SIGKILL)
        wait_until(lambda: not self.status(plan)['supervisor']['alive'])
        self.assertTrue(self.status(plan)['processes']['game']['alive'], 'the workload outlived its supervisor, as a process group mode allows')
        stopped = self.stop(plan)
        self.assertTrue(stopped['stopped'])
        self.assertTrue(stopped['escalated'])
        self.assertFalse(self.status(plan)['processes']['game']['alive'])


class Identity(GuestFixture):
    def test_a_reused_pid_is_not_our_process_and_is_never_signalled(self):
        self.fence()
        plan = self.plan()
        started = self.start(plan)
        os.kill(started['supervisor']['pid'], signal.SIGKILL)
        wait_until(lambda: not self.status(plan)['supervisor']['alive'])
        os.killpg(started['processes']['game']['pid'], signal.SIGKILL)
        # An unrelated process is given the numbers of the dead workload, as the kernel may do with a pid.
        stranger = subprocess.Popen([sys.executable, '-c', 'import os,time; os.setsid(); time.sleep(60)'])
        self.addCleanup(lambda: (stranger.kill(), stranger.wait()))
        tree = self.tree(plan)
        identity = json.loads((tree / 'identity.json').read_text())
        identity['processes']['game']['pid'] = stranger.pid
        identity['processes']['sampler']['pid'] = stranger.pid
        (tree / 'identity.json').write_text(json.dumps(identity))
        summary = self.status(plan)
        self.assertFalse(summary['processes']['game']['alive'], 'same pid, different start time: not ours')
        stopped = self.stop(plan)
        self.assertTrue(stopped['stopped'])
        self.assertIsNone(stranger.poll(), 'the stranger keeps running')

    def test_same_process_compares_the_kernel_start_time(self):
        me = guest_runner.identity_of(os.getpid())
        self.assertTrue(guest_runner.same_process(me))
        self.assertFalse(guest_runner.same_process(dict(me, start_id='ticks:1')))
        self.assertFalse(guest_runner.same_process(dict(me, start_id=None)))

    def test_linux_process_identity_reads_the_kernel_start_field(self):
        with tempfile.TemporaryDirectory() as proc:
            directory = pathlib.Path(proc) / '4242'
            directory.mkdir()
            fields = ['S'] + ['0'] * 18 + ['987654'] + ['0'] * 30
            (directory / 'stat').write_text('4242 (omega server) ' + ' '.join(fields))
            self.assertEqual(guest_runner.process_start_id(4242, proc), 'ticks:987654')
            fields[0] = 'Z'
            (directory / 'stat').write_text('4242 (omega server) ' + ' '.join(fields))
            self.assertIsNone(guest_runner.process_start_id(4242, proc), 'a zombie has exited')
            self.assertIsNone(guest_runner.process_start_id(1, proc), 'no such pid')

    def test_linux_socket_rows_are_per_socket_and_owned_by_the_exact_process(self):
        self.assertEqual(guest_runner.parse_proc_net_udp(PROC_NET_UDP, 8081), [dict(local='00000000:1F91', inode='91234', drops=7, rx_queue=512)])
        with tempfile.TemporaryDirectory() as proc:
            root = pathlib.Path(proc)
            (root / 'net').mkdir()
            (root / 'net' / 'udp').write_text(PROC_NET_UDP)
            (root / 'net' / 'udp6').write_text('  sl\n')
            fd = root / '4242' / 'fd'
            fd.mkdir(parents=True)
            os.symlink('socket:[91234]', str(fd / '7'))
            self.assertEqual(guest_runner.observe_socket(4242, 8081, str(root))['inode'], '91234')
            self.assertIsNone(guest_runner.observe_socket(4242, 8082, str(root)), 'that socket belongs to someone else')


class Counters(unittest.TestCase):
    PLAN = dict(watch_socket_port=8081, processes=[dict(name='game')])

    def summary(self, first, last, pid=10, start='ticks:1'):
        row = dict(pid=pid, start_id=start, inode='91', drops=0)
        return dict(socket=dict(first=dict(row, **first), last=dict(row, **last)), processes=dict(game=dict(pid=pid, start_id=start)))

    def test_clean_counters_pass(self):
        self.assertEqual(run_checks.socket_problems(self.PLAN, self.summary(dict(drops=2), dict(drops=5)), [], True), [])

    def test_a_counter_that_moved_backward_is_refused(self):
        self.assertIn('the game socket counter moved backward', run_checks.socket_problems(self.PLAN, self.summary(dict(drops=9), dict(drops=2)), [], True))

    def test_counters_from_an_earlier_socket_are_refused(self):
        ledger = [dict(run_id='old', sealed=True, socket_inodes=['91'])]
        self.assertIn('the game socket has the identity of an earlier run', run_checks.socket_problems(self.PLAN, self.summary({}, {}), ledger, True))

    def test_a_row_from_another_process_is_refused(self):
        problems = run_checks.socket_problems(self.PLAN, self.summary({}, dict(pid=11)), [], True)
        self.assertIn('a socket counter row belongs to a different process', problems)

    def test_a_socket_replaced_during_the_run_cannot_be_compared(self):
        self.assertIn('the game socket changed during the run: counters cannot be compared', run_checks.socket_problems(self.PLAN, self.summary({}, dict(inode='92')), [], True))

    def test_a_missing_counter_fails_where_counters_are_required(self):
        self.assertIn('the game socket has no drop counter', run_checks.socket_problems(self.PLAN, self.summary(dict(drops=None), dict(drops=None)), [], True))
        self.assertEqual(run_checks.socket_problems(self.PLAN, self.summary(dict(drops=None), dict(drops=None)), [], False), [])

    def test_a_socket_never_seen_is_a_failure(self):
        self.assertEqual(run_checks.socket_problems(self.PLAN, dict(socket=None), [], False), ['the game socket was never observed'])


class Sealing(GuestFixture):
    def test_seal_inventories_every_byte_and_makes_the_tree_read_only(self):
        self.fence()
        plan = self.plan()
        self.start(plan)
        wait_until(lambda: self.status(plan)['socket'])
        self.stop(plan)
        sealed = self.seal(plan)
        tree = self.tree(plan)
        listed = {item['path']: item['sha256'] for item in sealed['seal']['files']}
        for name, digest in listed.items():
            self.assertEqual(run_executor.sha256_path(tree / name), digest)
        self.assertEqual({'plan.json', 'identity.json', 'result.json', 'final.json', 'sockets.ndjson', 'game-summary.json', 'game.stdout.log', 'game.stderr.log'} - set(listed), set())
        self.assertEqual(run_executor.sha256_path(tree / guest_runner.SEAL), sealed['seal_sha256'])
        with self.assertRaises(PermissionError):
            (tree / 'result.json').write_text('{}')
        with self.assertRaises(PermissionError):
            (tree / 'new-file').write_text('x')

    def test_seal_refuses_while_anything_runs(self):
        self.fence()
        plan = self.plan()
        self.start(plan)
        self.assertEqual(self.seal(plan)['code'], 'still_running')

    def test_sealing_twice_returns_the_same_seal(self):
        self.fence()
        plan = self.plan()
        self.start(plan)
        self.stop(plan)
        self.assertEqual(self.seal(plan)['seal_sha256'], self.seal(plan)['seal_sha256'])

    def test_an_interrupted_run_is_sealed_and_says_so(self):
        self.fence()
        plan = self.plan()
        self.start(plan)
        self.fence(token=2)
        self.stop(plan, token=2, reason='controller_replaced')
        sealed = self.seal(plan, 2, '--interrupted', 'controller_replaced')
        self.assertEqual(sealed['seal']['interrupted'], 'controller_replaced')
        self.assertTrue(sealed['result']['stop_reason'].startswith('stop_requested:controller_replaced'))
        self.assertIsNone(self.do('game', 'inspect')['active'], 'the host is free again, with the evidence kept')

    def test_a_crash_after_the_seal_still_ends_read_only_and_inactive(self):
        self.fence()
        plan = self.plan()
        self.start(plan)
        self.stop(plan)
        sealed = self.seal(plan)
        tree = self.tree(plan)
        os.chmod(str(tree), 0o750)
        os.chmod(str(tree / 'result.json'), 0o640)
        (self.guests.runner_root('game') / 'control' / 'active.json').write_text(json.dumps(dict(run_id=plan['run_id'], role='game')))
        again = self.seal(plan)
        self.assertEqual(again['seal_sha256'], sealed['seal_sha256'])
        self.assertEqual(os.stat(str(tree / 'result.json')).st_mode & 0o777, 0o440)
        self.assertIsNone(self.do('game', 'inspect')['active'])


class Contract(GuestFixture):
    """The fake remote must promise only what the real runner delivers."""

    def test_the_fake_documents_have_the_keys_of_the_real_ones(self):
        self.fence()
        plan = self.plan()
        self.assertEqual(set(self.do('game', 'preflight', '--plan-json', json.dumps(plan))), set(fake_run_guest.CONTRACT_KEYS['preflight']))
        self.start(plan)
        wait_until(lambda: self.status(plan)['socket'])
        self.assertEqual(set(self.status(plan)), set(fake_run_guest.CONTRACT_KEYS['status']))
        self.assertEqual(set(self.do('game', 'inspect')), set(fake_run_guest.CONTRACT_KEYS['inspect']))


class SystemdPath(GuestFixture):
    """Through shims for ``sudo``, ``systemd-run`` and ``systemctl``, which run the real supervisor. Real units are a Gate A check."""

    def setUp(self):
        super().setUp()
        bin_dir = self.hosts.bin_dir
        self.record = self.root / 'systemd-argv.txt'
        (bin_dir / 'sudo').write_text('#!/bin/sh\nshift\nexec "$@"\n')
        (bin_dir / 'systemd-run').write_text('#!/bin/sh\necho "$@" >> "%s"\nwhile [ "${1#--}" != "$1" ]; do shift; done\nINVOCATION_ID=fixture-invocation-$$ nohup "$@" >/dev/null 2>&1 &\n' % self.record)
        (bin_dir / 'systemctl').write_text('#!/bin/sh\nif [ "$1" = "list-units" ]; then exit 0; fi\necho ActiveState=active\necho InvocationID=shim\n')
        for name in ('sudo', 'systemd-run', 'systemctl'):
            (bin_dir / name).chmod(0o755)

    def test_the_unit_carries_its_own_bound_and_the_run_records_the_invocation(self):
        self.fence()
        plan = self.plan(unit_mode=guest_runner.SYSTEMD, bound_s=30.0, stop_grace_s=1.0)
        started = self.start(plan)
        self.assertTrue(started['ok'], started)
        self.assertTrue(started['invocation_id'].startswith('fixture-invocation-'))
        argv = self.record.read_text()
        self.assertIn('--unit=' + plan['unit'], argv)
        self.assertIn('--property=RuntimeMaxSec=36', argv)
        self.assertIn('--property=KillMode=control-group', argv)
        self.assertIn('--property=Restart=no', argv)
        self.assertEqual(self.status(plan)['unit']['InvocationID'], 'shim')
        ledger = [dict(run_id='old', invocation_id=started['invocation_id'])]
        self.assertIn('the unit invocation was already used by an earlier run', run_checks.launch_problems(plan, started, ledger))
        self.assertEqual(self.stop(plan)['stopped'], True)

    def test_a_failed_unit_start_is_refused(self):
        (self.hosts.bin_dir / 'systemd-run').write_text('#!/bin/sh\nexit 1\n')
        self.fence()
        document = self.start(self.plan(unit_mode=guest_runner.SYSTEMD))
        self.assertEqual(document['code'], 'unit_start_failed')

    def test_leftover_units_fail_the_host_rules(self):
        plan = self.plan(unit_mode=guest_runner.SYSTEMD)
        facts = dict(units=['omega-run-abc-game.service'], files=[], ports_free={}, leftovers=[], impairment=dict(available=True, qdisc_kinds=['mq'], filter_count=0))
        self.assertIn('units remain: omega-run-abc-game.service', run_checks.host_problems(plan, facts, None, None))


if __name__ == '__main__':
    unittest.main()
