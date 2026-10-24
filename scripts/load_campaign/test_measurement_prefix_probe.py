"""Exercise the actual generated preflight command while its input file changes."""
import contextlib
import hashlib
import io
import json
import pathlib
import shlex
import tempfile
import unittest
from unittest.mock import patch

import native_diagnostic_r4 as probe
import native_diagnostic_r3 as earlier_probe


class MeasurementPrefixTests(unittest.TestCase):
    def run_probe(self, change, module=probe):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp).resolve()
            current, results = root/'current', root/'results'
            current.mkdir(); results.mkdir()
            executable = root/'original-exe'
            executable.write_bytes(b'ELF-fixture')
            target = current/'server.ndjson'
            initial, extra = b'{"tick":1}\n', b'{"tick":2}\n'
            target.write_bytes(initial)
            code = shlex.split(module.rename_probe_command(1))[2]
            for old,new in (('/var/lib/omega-measure/current', current),
                            ('/home/deploy/omega-results', results),
                            ('/home/deploy/omega-stabilized-b1266c1/rust/target/release/omega-server', executable)):
                code = code.replace(old, str(new))
            original_open = pathlib.Path.open
            changed = False

            def mutate():
                nonlocal changed
                if changed:
                    return
                changed = True
                if change == 'append':
                    with original_open(target, 'ab') as writer:writer.write(extra)
                elif change == 'truncate':
                    with original_open(target, 'wb') as writer:writer.write(initial[:-1])
                elif change == 'replace':
                    target.unlink()
                    with original_open(target, 'wb') as writer:writer.write(initial)

            class Reader:
                def __init__(self, stream):self.stream = stream
                def __enter__(self):return self
                def __exit__(self, *args):self.stream.close()
                def fileno(self):return self.stream.fileno()
                def readable(self):return True
                def read(self, size=-1):mutate(); return self.stream.read(size)
                def readinto(self, data):mutate(); return self.stream.readinto(data)

            def open_file(path, *args, **kwargs):
                stream = original_open(path, *args, **kwargs)
                return Reader(stream) if path == target and args == ('rb',) else stream

            output = io.StringIO()
            with patch.object(pathlib.Path, 'open', open_file), contextlib.redirect_stdout(output):
                exec(compile(code, 'actual-prefix-probe', 'exec'), {})
            row = json.loads(output.getvalue())['measurement']['files']['server.ndjson']
            with original_open(target, 'rb') as stream:
                release_sha = hashlib.sha256(stream.read(row['bytes'])).hexdigest()
            return row, initial, release_sha

    def test_appending_during_real_probe_keeps_size_and_hash_on_same_prefix(self):
        for module in (probe, earlier_probe):
            with self.subTest(module=module.__name__):
                row, initial, release_sha = self.run_probe('append', module)
                self.assertEqual(row['bytes'], len(initial))
                self.assertEqual(row['sha256'], hashlib.sha256(initial).hexdigest())
                self.assertEqual(row['sha256'], release_sha)

    def test_truncation_during_acquisition_fails_closed(self):
        for module in (probe, earlier_probe):
            with self.subTest(module=module.__name__), self.assertRaises(RuntimeError):
                self.run_probe('truncate', module)

    def test_path_replacement_during_acquisition_fails_closed(self):
        for module in (probe, earlier_probe):
            with self.subTest(module=module.__name__), self.assertRaises(RuntimeError):
                self.run_probe('replace', module)
