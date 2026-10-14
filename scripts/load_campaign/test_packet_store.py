import pathlib
import io
import struct
import unittest
from packet_store import PacketStore
from analyze import packet_observations


class PacketStoreTests(unittest.TestCase):
    @staticmethod
    def record(stamp, source, target, kind, sequence=0, related=0):
        command = bytearray(16)
        command[0], command[1], command[12] = kind, 1, 67
        struct.pack_into('>HHH', command, 2, sequence, related, 1)
        return (struct.pack('<Q', stamp) + struct.pack('>HH', source, target)
                + struct.pack('<HHQH', 40, 20, stamp, 1) + command)

    def test_egress_mirror_cannot_claim_unacknowledged_queue(self):
        data = b'ORF1' + self.record(1, 8081, 40000, 0x86, sequence=1)
        result, _ = packet_observations(io.BytesIO(data), 0, 10, track_outstanding=False)
        self.assertIsNone(result['out']['outstanding_commands_end'])
        self.assertEqual(result['out']['reliable_commands'], 1)

    def test_bidirectional_endpoint_observes_returning_ack(self):
        data = (b'ORF1' + self.record(1, 8081, 40000, 0x86, sequence=1)
                + self.record(2, 40000, 8081, 1, related=1))
        result, _ = packet_observations(io.BytesIO(data), 0, 10)
        self.assertEqual(result['out']['outstanding_commands_end'], 0)
        self.assertEqual(result['in']['acks'], 1)

    def test_duplicates_loss_clock_margin_and_late_boundary_arrival(self):
        with PacketStore() as store:
            sender, receiver = store.contexts(), store.contexts()
            key, missing = (8081, 40000, 50, 7), (8081, 40001, 50, 9)
            for stamp in (900_000_000, 1_000_000_000, 1_100_000_000, 1_200_000_000, 2_999_999_999):
                sender['out'].add(key, stamp)
            for stamp in (900_000_100, 998_000_000, 1_150_000_000, 3_500_000_000):
                receiver['out'].add(key, stamp)
            sender['out'].add(missing, 1_400_000_000)
            store.prepare()
            result = store.match(sender['out'], receiver['out'], 1_000_000_000, 3_000_000_000)
            self.assertEqual((result['sent'], result['matched'], result['unmatched']), (5, 3, 2))
            self.assertEqual(result['delay_ms']['p50'], 50.0)
            self.assertEqual(result['delay_ms']['p95'], 500.000001)
            self.assertAlmostEqual(result['delay_ms']['mean'], 182.666667)

    def test_unsigned_fingerprint_and_port_limits_round_trip(self):
        with PacketStore() as store:
            contexts = store.contexts()
            key = (8081, 65535, 65535, 2**64 - 1)
            contexts['in'].add(key, 1_791_943_000_000_000_000)
            store.prepare()
            self.assertEqual(list(contexts['in'].items()), [(key, [1_791_943_000_000_000_000])])

    def test_temporary_evidence_removed_on_failure(self):
        location = None
        with self.assertRaisesRegex(RuntimeError, 'injected'):
            with PacketStore() as store:
                location = pathlib.Path(store.directory.name)
                store.contexts()['out'].add((8081, 40000, 50, 7), 1)
                raise RuntimeError('injected')
        self.assertFalse(location.exists())


if __name__ == '__main__':
    unittest.main()
