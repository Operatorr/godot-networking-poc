"""Wire replay verifies ramp counts without a steady window and 10ms aggregation."""
import csv
import pathlib
import subprocess
import unittest
from test_article_flow import ArticleFlowTests

class ControlFlowTests(ArticleFlowTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        subprocess.run(['rustc', '--edition=2021', '-O', str(pathlib.Path(__file__).with_name('udp_control_record.rs')), '-o', str(cls.binary)], check=True)

    def test_ramp_port_and_burst_counts_without_window(self):
        import struct
        payload = b'\x00\x01' + struct.pack('>BBHHH', 7, 2, 1, 1, 22) + b'\x02' + bytes(21)
        directory, _ = self.replay(True, [(9.001, 40000, payload), (9.002, 40001, payload), (9.003, 40000, payload), (10.02, 40000, payload)])
        rows = list(csv.DictReader((directory/'input-ports.csv').read_text().splitlines()))
        self.assertEqual([(r['utc_second'],r['port'],r['input_commands']) for r in rows], [('9','40000','2'),('9','40001','1'),('10','40000','1')])
        bins = list(csv.DictReader((directory/'flow-bins.csv').read_text().splitlines()))
        self.assertEqual([int(r['inputs']) for r in bins], [3,1])
        self.assertEqual(sum(int(r['in_packets']) for r in bins),4)

    def test_unsigned_handshake_maps_port_without_retaining_name(self):
        import struct
        body = bytes([1,7,0,0,10]) + b'LoadBot007'
        payload = b'\x00\x01' + struct.pack('>BBHH', 0x86, 1, 1, len(body)) + body
        directory, _ = self.replay(True, [(9.1, 40000, payload)])
        self.assertEqual((directory/'port-bot.csv').read_text(), 'port,bot_id\n40000,7\n')

    def test_partial_pcap_is_error_and_retains_prefix_evidence(self):
        import json
        import struct
        import tempfile
        directory = pathlib.Path(tempfile.mkdtemp(dir=self.temp.name))
        # One complete valid handshake, then an incomplete record header.
        body = bytes([1, 7, 0, 0, 10]) + b'LoadBot007'
        payload = b'\x00\x01' + struct.pack('>BBHH', 0x86, 1, 1, len(body)) + body
        udp = struct.pack('>HHHH', 40000, 8081, len(payload) + 8, 0) + payload
        ip = bytearray(20)
        ip[0] = 0x45
        ip[9] = 17
        ip[2:4] = struct.pack('>H', 20 + len(udp))
        frame = bytes(12) + b'\x08\x00' + ip + udp
        pcap = struct.pack('<IHHIIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)
        pcap += struct.pack('<IIII', 9, 0, len(frame), len(frame)) + frame + b'\x01'
        result = subprocess.run([str(self.binary), str(directory), '--article'], input=pcap, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        status = json.loads((directory/'parser-status.json').read_text())
        self.assertEqual(status['status'], 'error')
        self.assertEqual(status['packets'], 1)
        self.assertEqual(status['parse_errors'], 0)
        self.assertEqual(status['last_read_record_utc_ns'], 9_000_000_000)
        self.assertEqual((directory/'port-bot.csv').read_text(), 'port,bot_id\n40000,7\n')
        summary = json.loads((directory/'flow-summary.json').read_text())
        self.assertEqual(summary['format'], 'udp-diagnostic-points-v2')
        self.assertEqual(summary['reliable_history_bytes'], 4096)
        self.assertEqual(summary['unclassified_reliable_all_capture'], [0, 0])

    def test_eof_status_does_not_hide_malformed_packets(self):
        import json
        directory, _ = self.replay(True, [(9.1, 40000, b'\x00')])
        status = json.loads((directory/'parser-status.json').read_text())
        self.assertEqual(status['status'], 'eof')
        self.assertEqual(status['packets'], 1)
        self.assertEqual(status['parse_errors'], 1)

if __name__ == '__main__':
    unittest.main()
