"""The operator CLI wires the real checks, and it offers no way around them."""
import contextlib
import io
import json
import pathlib
import unittest

import manifest as manifest_mod
import run_cli
import run_fixtures as rf


class Cli(unittest.TestCase):
    def setUp(self):
        self.sim = rf.RunSim(self)
        self.addCleanup(rf.make_writable, self.sim.stack.root)
        self.sim.ready()
        root = pathlib.Path(self.sim.stack.root)
        (root / 'manifest.json').write_text(manifest_mod.canonical_json(self.sim.manifest))
        (root / 'manifest.sha256').write_text(self.sim.sha + '  manifest.json\n')
        self.common = ['--session-dir', str(root), '--token-file', 'unused', '--registry-command', 'unused', '--ssh-key', 'unused']
        client = rf.pf.client_for(self.sim, 'cli-controller')
        self.environment = dict(transport=lambda path: self.sim.account, guests=lambda key, session_dir: self.sim.guests, registry=lambda command: client)

    def run_cli(self, *arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = run_cli.main(list(arguments) + self.common, environment=self.environment)
        return code, json.loads(output.getvalue())

    def test_resume_checks_the_real_controller_revision(self):
        code, document = self.run_cli('resume', '--operator-request', 'operator: test', '--takeover')
        self.assertEqual(code, 2)
        self.assertFalse(document['resume']['resumed'])
        self.assertEqual(document['resume']['code'], 'source_changed', 'the fixture manifest names a revision this checkout is not')
        self.assertIsNone(document['batch'])

    def test_resume_without_takeover_respects_a_live_lease(self):
        code, document = self.run_cli('resume', '--operator-request', 'operator: test')
        self.assertEqual(code, 2)
        self.assertEqual(document['resume']['code'], 'control_held')

    def test_a_stale_token_runs_nothing(self):
        self.sim.controller()
        code, document = self.run_cli('execute', '--fencing-token', str(self.sim.result.fencing_token))
        self.assertEqual(code, 2)
        self.assertEqual(document['status'], 'control_lost')
        self.assertEqual(self.sim.guests.starts(), [])

    def test_the_parser_offers_no_scorer_and_requires_an_operator_request(self):
        for argv in (['resume'] + self.common, ['resume', '--operator-request', 'x', '--scorer', 'y'] + self.common, ['execute'] + self.common):
            with self.subTest(argv=argv[:2]), self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                run_cli.main(argv, environment=self.environment)

    def test_collect_ends_in_a_cleanup_request(self):
        code, document = self.run_cli('collect', '--reason', 'operator chose to stop', '--takeover')
        self.assertEqual(document['batch']['code'], 'operator_collect')
        self.assertEqual(code, 0, document)
        self.assertIsNotNone(self.sim.status_now()['cleanup']['requested_at'])


if __name__ == '__main__':
    unittest.main()
