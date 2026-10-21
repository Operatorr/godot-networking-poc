"""Exercise actual filesystem visibility while a simulated scp is incomplete."""
import json
import pathlib
import subprocess
import tempfile
import unittest

from atomic_publish import publish_file


class AtomicPublicationTests(unittest.TestCase):
    def test_reader_sees_old_window_until_complete_replacement(self):
        with tempfile.TemporaryDirectory(prefix='omega window ') as root:
            root = pathlib.Path(root)
            source, destination = root/'source.json', root/'window.json'
            source.write_text('{"start": 200, "end": 500}')
            destination.write_text('{"start": 100, "end": 400}')

            def copy(_role, local, remote):
                with pathlib.Path(remote).open('w') as target:
                    target.write('{')
                    target.flush()
                    self.assertEqual(json.loads(destination.read_text()), {'start': 100, 'end': 400})
                    target.seek(0)
                    target.write(pathlib.Path(local).read_text())
                    target.truncate()

            def ssh(_role, command):
                subprocess.run(command, shell=True, check=True)

            publish_file(copy, ssh, 'game', source, str(destination))
            self.assertEqual(json.loads(destination.read_text()), {'start': 200, 'end': 500})
            self.assertFalse(pathlib.Path(str(destination)+'.partial').exists())

    def test_failed_transfer_never_publishes_initial_window(self):
        with tempfile.TemporaryDirectory() as root:
            destination = pathlib.Path(root)/'window.json'

            def copy(_role, _local, remote):
                pathlib.Path(remote).write_text('{')
                self.assertFalse(destination.exists())
                raise OSError('transfer interrupted')

            def ssh(*_args):
                self.fail('must not rename after failed transfer')

            with self.assertRaises(OSError):
                publish_file(copy, ssh, 'game', 'unused', str(destination))
            self.assertFalse(destination.exists())


if __name__ == '__main__':
    unittest.main()
