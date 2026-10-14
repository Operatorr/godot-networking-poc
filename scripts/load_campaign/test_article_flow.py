"""Replay real wire-shaped traffic through both recorder modes, including retries/wrap."""
import io
import json
import pathlib
import struct
import subprocess
import tempfile
import unittest

import analyze


class ArticleFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.binary = pathlib.Path(cls.temp.name) / 'flow-record'
        subprocess.run(['rustc', '--edition=2021', '-O', str(pathlib.Path(__file__).with_name('flow_record.rs')),
                        '-o', str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def replay(self, compact, frames):
        directory = pathlib.Path(tempfile.mkdtemp(dir=self.temp.name))
        window = {'start': 10_250_000_000, 'end': 12_250_000_000}
        (directory / 'window.json').write_text(json.dumps(window))
        pcap = struct.pack('<IHHIIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)
        for stamp, source, payload in frames:
            target = 40000 if source == 8081 else 8081
            udp = struct.pack('>HHHH', source, target, len(payload) + 8, 0) + payload
            ip = bytearray(20); ip[0] = 0x45; ip[9] = 17; ip[2:4] = struct.pack('>H', 20 + len(udp))
            frame = bytes(12) + b'\x08\x00' + ip + udp
            pcap += struct.pack('<IIII', int(stamp), int(stamp % 1 * 1e6), len(frame), len(frame)) + frame
        command = [str(self.binary), str(directory)] + (['--article'] if compact else [])
        subprocess.run(command, input=pcap, capture_output=True, check=True)
        return directory, window

    def test_exact_counts_boundaries_retries_and_sequence_wrap_with_small_sample(self):
        frames = []
        for index in range(1000):
            stamp = 9 + index / 250
            sequence = (65500 + index) % 65536
            payload = b'\x00\x01' + struct.pack('>BBHH', 7, 2, sequence, 0) + struct.pack('>H', 22) + b'\x02' + bytes(21)
            frames.append((stamp, 40000, payload))
            reliable = b'\x00\x01' + struct.pack('>BBHH', 0x86, 1, sequence, 2) + b'\x41\x00'
            frames.extend([(stamp, 8081, reliable), (stamp + .001, 8081, reliable)])
        frames.sort()
        full, window = self.replay(False, frames)
        compact, _ = self.replay(True, frames)
        with (full / 'datagrams.bin').open('rb') as stream:
            expected = analyze.packet_observations(stream, window['start'], window['end'])[0]
        actual = json.loads((compact / 'flow-summary.json').read_text())
        for direction in ('out', 'in'):
            for key, value in expected[direction].items():
                if key != 'outstanding_commands_end':
                    converted = {str(k): v for k, v in value.items()} if isinstance(value, dict) else value
                    self.assertEqual(actual[direction][key], converted, key)
        self.assertEqual(actual['wire_input_counts_by_port'], {str(k): v for k, v in expected['wire_input_counts_by_port'].items()})
        self.assertTrue(analyze.capture_covers_window(actual, window['start'], window['end']))
        self.assertFalse((compact / 'headers.pcap').exists())
        self.assertLess((compact / 'datagrams.bin').stat().st_size, (full / 'datagrams.bin').stat().st_size / 20)
        with (compact / 'datagrams.bin').open('rb') as stream:
            self.assertTrue(all(not row[-1] for row in analyze.records(stream)))
        retry = subprocess.run([str(self.binary), str(compact), '--article'], input=b'', capture_output=True)
        self.assertNotEqual(retry.returncode, 0)


if __name__ == '__main__':
    unittest.main()
