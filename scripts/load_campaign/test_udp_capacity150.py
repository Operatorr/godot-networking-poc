"""Controller regression checks without contacting a host or launching traffic."""
import json
import pathlib
import tempfile
import unittest
from unittest import mock
from atomic_publish import publish_file
import udp_capacity150 as controller

class CapacityControllerTests(unittest.TestCase):
    def test_direct_copy_exposes_partial_json_and_atomic_publication_does_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory);source=root/'source';destination=root/'window.json'
            source.write_text('{"start":60000000000,"end":360000000000}')
            def copy(role,src,dst):
                pathlib.Path(dst).write_text('{')
                if pathlib.Path(dst)==destination:
                    with self.assertRaises(json.JSONDecodeError):json.loads(destination.read_text())
                else:self.assertFalse(destination.exists())
                pathlib.Path(dst).write_bytes(pathlib.Path(src).read_bytes())
            copy('game',source,destination)
            # Separate namespace for the corrected first publication.
            destination=root/'new-window.json'
            def rename(role,cmd):
                pathlib.Path(str(destination)+'.partial').rename(destination)
            publish_file(copy,rename,'game',source,destination)
            self.assertEqual(json.loads(destination.read_text())['end'],360000000000)

    def test_tail_reader_ignores_in_progress_partial_row(self):
        with tempfile.TemporaryDirectory() as directory:
            path=pathlib.Path(directory)/'rows'
            path.write_text('{"utc_ns":1}\n{"utc_ns":')
            self.assertEqual(controller.tail_json(path),{'utc_ns':1})

    def test_frozen_bounds(self):
        self.assertEqual(controller.STEADY_SECONDS,360)
        self.assertEqual(controller.RAMP_SECONDS,180)

if __name__=='__main__':unittest.main()
