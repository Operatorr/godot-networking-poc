"""The operator CLI end to end, offline: refusal order, planner journal wiring and source digests."""
import contextlib
import hashlib
import io
import json
import os
import pathlib
import subprocess
import tempfile
import unittest
import unittest.mock

import do_session
import evidence_publication
import provision_cli
import provision_fixtures as pf
import provisioner
import remote_authorization
import session_clock

REPO = pathlib.Path(__file__).parents[2]


class Cli(unittest.TestCase):
    def setUp(self):
        self.sim = pf.Sim(self, durable_destination=evidence_publication.AMENDED_DESTINATION)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = pathlib.Path(directory.name)
        self.session_dir = self.root / self.sim.session_id
        self.session_dir.mkdir()
        (self.session_dir / 'manifest.json').write_text(json.dumps(self.sim.manifest, sort_keys=True))
        (self.session_dir / 'manifest.sha256').write_text(self.sim.sha + '  manifest.json\n')
        self.authorization = self.root / 'authorization.json'
        self.authorization.write_text(json.dumps(self.sim.packet))
        self.token_reads = []

        def transport(token_file):
            self.token_reads.append(str(token_file))
            return self.sim.account
        self.environment = provision_cli.Environment(transport_factory=transport, registry_factory=lambda command: self.sim.client,
                                                     guests_factory=lambda key, session: self.sim.guests, sleep=self.sim.sleep,
                                                     monotonic=self.sim.monotonic, wall=self.sim.clock.wall)

    def run_cli(self, *arguments):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = provision_cli.main(list(arguments), self.environment)
        return code, out.getvalue()

    def provision_args(self):
        return ('provision', '--session-dir', str(self.session_dir), '--token-file', '/nonexistent/token', '--registry-command', 'unused',
                '--authorization', str(self.authorization), '--ssh-key', '/nonexistent/key')

    def test_missing_authorization_stops_at_the_command_line(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                self.run_cli('provision', '--session-dir', str(self.session_dir), '--token-file', 'x', '--registry-command', 'y', '--ssh-key', 'z')
        self.assertEqual(self.token_reads, [])

    def test_refused_authorization_reads_no_token_and_sends_nothing(self):
        self.authorization.write_text(json.dumps(dict(self.sim.packet, max_pairs=2)))
        code, out = self.run_cli(*self.provision_args())
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)['code'], 'authorization_refused')
        self.assertEqual(self.token_reads, [])
        self.assertEqual(self.sim.account.requests, [])

    def test_a_capacity_session_with_no_accepted_evidence_destination_is_refused_before_anything_else(self):
        sim = pf.Sim(self, session_id='do-cap-legacy-bucket')     # the object-store reference the operator rejected in issue 63
        (self.session_dir / 'manifest.json').write_text(json.dumps(sim.manifest, sort_keys=True))
        (self.session_dir / 'manifest.sha256').write_text(sim.sha + '  manifest.json\n')
        self.authorization.write_text(json.dumps(sim.packet))
        code, out = self.run_cli(*self.provision_args())
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)['code'], 'authorization_refused')
        self.assertTrue(any('text model' in reason for reason in json.loads(out)['reasons']), out)
        self.assertEqual(self.token_reads, [])
        self.assertEqual(self.sim.account.requests, [])

    def test_an_altered_manifest_is_refused_before_anything_else(self):
        (self.session_dir / 'manifest.sha256').write_text('0' * 64 + '  manifest.json\n')
        with contextlib.redirect_stderr(io.StringIO()):
            code, _ = self.run_cli(*self.provision_args())
        self.assertEqual(code, 1)
        self.assertEqual(self.token_reads, [])

    def test_provision_reaches_ready_and_the_planner_adopts_the_registry_t0(self):
        code, out = self.run_cli(*self.provision_args())
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)['status'], provisioner.READY)
        _, _, _, meta = do_session.load_session(self.session_dir)
        self.assertEqual(meta['phase'], 'pair_ready')
        self.assertEqual(session_clock.parse(meta['t0']), session_clock.parse(self.sim.status()['t0_utc']))
        self.assertTrue((self.session_dir / 'arm-ack.json').exists())
        self.assertTrue((self.session_dir / 'provisioning' / 'readiness.json').exists())
        self.assertEqual(do_session.load_session(self.session_dir)[3]['ready_at'], meta['ready_at'])

    def test_a_stopped_provision_exits_nonzero_and_names_why(self):
        self.sim.guests.break_step('game', 'wait_cloud_init', rc=1, status='error')
        code, out = self.run_cli(*self.provision_args())
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)['code'], 'bootstrap_failed')
        self.assertEqual(do_session.load_session(self.session_dir)[3]['phase'], 'provisioning')

    def test_a_refresh_stopped_between_attempts_exits_nonzero_and_says_why(self):
        _, out = self.run_cli(*self.provision_args())
        ready = json.loads(out)
        self.sim.account.fault('PUT', '^/v2/firewalls/', 'status', status=503, times=1)
        puts = len(self.sim.puts())
        original = self.environment.sleep

        def abort_then_sleep(seconds):
            self.sim.stack.registry.operator_abort(self.sim.session_id, 'operator abort during refresh')
            original(seconds)
        self.environment.sleep = abort_then_sleep
        code, out = self.run_cli('refresh-access', '--session-dir', str(self.session_dir), '--token-file', 'x', '--registry-command', 'y', '--authorization', str(self.authorization),
                                 '--fencing-token', str(ready['fencing_token']), '--ssh-source', '198.51.100.250/32')
        self.assertEqual(code, 2, out)
        document = json.loads(out)
        self.assertEqual(document['applied'], False)
        self.assertTrue(document['stopped'])
        self.assertEqual(len(self.sim.puts()), puts + 1)

    def test_authorization_ending_mid_refresh_exits_nonzero_and_says_why(self):
        _, out = self.run_cli(*self.provision_args())
        ready = json.loads(out)
        self.sim.account.fault('PUT', '^/v2/firewalls/', 'status', status=503, times=1)
        puts = len(self.sim.puts())
        real_validate = remote_authorization.validate
        ended = []

        def validate(*arguments):
            return ['authorization is outside its time window'] if ended else real_validate(*arguments)
        self.environment.sleep = ended.append
        with unittest.mock.patch.object(remote_authorization, 'validate', validate):
            code, out = self.run_cli('refresh-access', '--session-dir', str(self.session_dir), '--token-file', 'x', '--registry-command', 'y', '--authorization', str(self.authorization),
                                     '--fencing-token', str(ready['fencing_token']), '--ssh-source', '198.51.100.250/32')
        self.assertEqual(code, 2, out)
        self.assertEqual(json.loads(out)['code'], 'mutation_refused')
        self.assertEqual(len(self.sim.puts()), puts + 1)

    def test_refresh_access_uses_the_api_alone(self):
        _, out = self.run_cli(*self.provision_args())
        ready = json.loads(out)
        before = len(self.sim.guests.commands)
        code, out = self.run_cli('refresh-access', '--session-dir', str(self.session_dir), '--token-file', 'x', '--registry-command', 'y', '--authorization', str(self.authorization),
                                 '--fencing-token', str(ready['fencing_token']), '--ssh-source', '198.51.100.250/32', '--udp-source', '198.51.100.250/32')
        self.assertEqual(code, 0, out)
        self.assertTrue(json.loads(out)['applied'])
        self.assertEqual(len(self.sim.guests.commands), before)

    def test_returning_after_the_lease_lapsed_acquires_control_and_pauses_the_session(self):
        self.run_cli(*self.provision_args())
        self.sim.clock.advance(100)
        self.sim.stack.watchdog.tick()
        arguments = ('refresh-access', '--session-dir', str(self.session_dir), '--token-file', 'x', '--registry-command', 'y', '--authorization', str(self.authorization),
                     '--ssh-source', '198.51.100.250/32')
        code, out = self.run_cli(*arguments)
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)['fencing_token'], 2)
        self.assertEqual(self.sim.status()['state'], provision_cli.provisioner.registry.PAUSED)

    def test_refresh_refuses_a_broad_source_with_no_request(self):
        _, out = self.run_cli(*self.provision_args())
        ready = json.loads(out)
        puts = len(self.sim.account.ops('PUT'))
        code, out = self.run_cli('refresh-access', '--session-dir', str(self.session_dir), '--token-file', 'x', '--registry-command', 'y', '--authorization', str(self.authorization),
                                 '--fencing-token', str(ready['fencing_token']), '--ssh-source', '0.0.0.0/0')
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)['code'], 'access_refused')
        self.assertEqual(len(self.sim.account.ops('PUT')), puts)

    def test_preflight_only_reads(self):
        code, out = self.run_cli('preflight', '--session-dir', str(self.session_dir), '--token-file', 'x', '--registry-command', 'y')
        self.assertEqual(code, 0, out)
        self.assertEqual(self.sim.account.mutations(), [])

    def test_source_digests_match_the_committed_objects(self):
        head = subprocess.run(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], stdout=subprocess.PIPE, check=True).stdout.decode().strip()
        digests = provision_cli.source_digests(REPO, head)
        self.assertEqual(digests['benchmark_sha'], head)
        lock = subprocess.run(['git', '-C', str(REPO), 'show', head + ':rust/Cargo.lock'], stdout=subprocess.PIPE, check=True).stdout
        self.assertEqual(digests['cargo_lock_sha256'], hashlib.sha256(lock).hexdigest())
        self.assertRegex(digests['content_sha256'], '^[0-9a-f]{64}$')

    def test_real_token_loading_refuses_a_loose_file_before_any_request(self):
        token = self.root / 'token'
        token.write_text('offline-fixture-value')
        os.chmod(str(token), 0o644)
        self.environment.transport_factory = provision_cli.do_api.HttpsTransport
        with contextlib.redirect_stderr(io.StringIO()):
            code, _ = self.run_cli('preflight', '--session-dir', str(self.session_dir), '--token-file', str(token), '--registry-command', 'y')
        self.assertEqual(code, 1)
        self.assertEqual(self.sim.account.requests, [])


if __name__ == '__main__':
    unittest.main()
