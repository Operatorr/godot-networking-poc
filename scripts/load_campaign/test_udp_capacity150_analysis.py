"""Validate boundary and socket attribution seams without any remote traffic."""
import unittest
from udp_capacity150_analysis import bracket,dist,sockets,udp
from udp_capacity150_journal import message

class EvidenceAnalysisTests(unittest.TestCase):
    def test_journald_message_byte_arrays(self):
        text='oversized unreliable packet (1202 B) on channel 0'
        self.assertEqual(message({'MESSAGE':list(text.encode())}),text)
        self.assertEqual(message({'MESSAGE':text}),text)

    def test_complete_brackets_required(self):
        data=[{'utc_ns':10},{'utc_ns':20},{'utc_ns':30}]
        self.assertIsNone(bracket(data,9,25))
        self.assertIsNone(bracket(data,15,31))
        self.assertEqual(bracket(data,15,25),(data[0],data[2]))

    def test_missing_tail_remains_unknown(self):
        self.assertIsNone(dist([None])['p99'])
        self.assertEqual(dist([0,None])['n'],1)

    def test_socket_drop_attribution(self):
        text='UNCONN 0 0 *:8081 *:* users:(("omega-server",pid=123,fd=8)) ino:987\n\t skmem:(r1920,rb4194304,t0,tb524288,f0,w0,o0,bl0,d7)\n'
        s=sockets(text)[0]
        self.assertEqual((s['pid'],s['inode'],s['d'],s['rb']),(123,987,7,4194304))
        self.assertEqual(udp('Udp: InDatagrams RcvbufErrors\nUdp: 400 7\n')['RcvbufErrors'],7)

if __name__=='__main__':unittest.main()
