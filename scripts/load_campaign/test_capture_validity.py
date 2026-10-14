"""A clean tcpdump exit must not make a restarted/truncated capture valid."""
import io
import pathlib
import runpy
import struct
import sys
import tempfile
import unittest
from unittest import mock

import analyze


class CaptureValidityTests(unittest.TestCase):
    START = 70_000_000_000
    END = START + 300_000_000_000

    def observe(self, stamps):
        # Real ORF1 records, with no parser/kernel error indicators and no backsteps.
        data = b'ORF1' + b''.join(struct.pack('<Q', stamp) + struct.pack('>HH', 40000, 8081)
            + struct.pack('<HHQH', 40, 12, stamp, 0) for stamp in stamps)
        return analyze.packet_observations(io.BytesIO(data), self.START, self.END)[0]

    def test_full_capture_spans_warmup_and_measurement(self):
        packets = self.observe([0, self.START, self.END + 1_000_000])
        self.assertTrue(analyze.capture_covers_window(packets, self.START, self.END))

    def test_restarted_capture_missing_first_202_seconds_is_invalid(self):
        packets = self.observe([self.START + 202_000_000_000, self.END + 1_000_000])
        self.assertEqual(packets['max_timestamp_backstep_ns'], 0)
        self.assertFalse(analyze.capture_covers_window(packets, self.START, self.END))

    def test_interrupted_capture_missing_tail_is_invalid(self):
        packets = self.observe([0, self.START, self.END - 120_000_000_000])
        self.assertFalse(analyze.capture_covers_window(packets, self.START, self.END))

    def test_empty_capture_is_invalid(self):
        packets = self.observe([])
        self.assertFalse(analyze.capture_covers_window(packets, self.START, self.END))

    def test_capture_restart_preserves_original_log_and_does_not_spawn(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = pathlib.Path(temporary)
            log = directory / 'capture.log'
            log.write_text('first generation capture evidence\n')
            script = pathlib.Path(__file__).with_name('capture.py')
            with mock.patch.object(sys, 'argv', [str(script), str(directory), 'eth0', '192.0.2.1']), \
                 mock.patch('subprocess.Popen', side_effect=RuntimeError('unexpected capture launch')) as launch:
                with self.assertRaises(FileExistsError):
                    runpy.run_path(str(script), run_name='__main__')
            self.assertEqual(log.read_text(), 'first generation capture evidence\n')
            launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
