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

if __name__ == '__main__':
    unittest.main()
