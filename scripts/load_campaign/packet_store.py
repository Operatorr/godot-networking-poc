"""Disk-backed exact packet matching and delay quantiles for large captures."""
import collections
import hashlib
import itertools
import math
import pathlib
import sqlite3
import struct
import tempfile

SOURCE_BYTES = pathlib.Path(__file__).read_bytes()
SOURCE_SHA256 = hashlib.sha256(SOURCE_BYTES).hexdigest()


class MemoryContext(collections.defaultdict):
    def __init__(self):
        super().__init__(list)

    def add(self, key, stamp):
        self[key].append(stamp)


class PacketContext:
    def __init__(self, store, identifier):
        self.store, self.identifier = store, identifier

    def add(self, key, stamp):
        self.store.pending.append((self.identifier, struct.pack('>HHHQ', *key), stamp))
        if len(self.store.pending) >= 8192:
            self.store.flush()

    def items(self):
        cursor = self.store.db.execute('SELECT key, stamp FROM packets WHERE context=? ORDER BY key, ordinal', (self.identifier,))
        try:
            for key, group in itertools.groupby(cursor, lambda row: row[0]):
                yield struct.unpack('>HHHQ', key), [row[1] for row in group]
        finally:
            cursor.close()


class PacketStore:
    def __enter__(self):
        self.directory = tempfile.TemporaryDirectory(prefix='omega-packet-analysis-')
        self.db = sqlite3.connect(str(pathlib.Path(self.directory.name) / 'packets.sqlite'))
        self.db.execute('PRAGMA cache_size=-32768')
        self.db.execute('PRAGMA temp_store=FILE')
        self.db.execute('PRAGMA journal_mode=OFF')
        self.db.execute('CREATE TABLE packets (ordinal INTEGER PRIMARY KEY, context INTEGER, key BLOB, stamp INTEGER)')
        self.db.execute('CREATE TABLE delays (context INTEGER, ns INTEGER)')
        self.pending, self.next_context = [], 0
        return self

    def __exit__(self, *_):
        self.db.close()
        self.directory.cleanup()

    def flush(self):
        self.db.executemany('INSERT INTO packets (context,key,stamp) VALUES (?,?,?)', self.pending)
        self.pending.clear()

    def contexts(self):
        result = {}
        for direction in ('out', 'in'):
            result[direction] = PacketContext(self, self.next_context)
            self.next_context += 1
        return result

    def prepare(self):
        self.flush()
        self.db.execute('CREATE INDEX packet_keys ON packets (context,key,ordinal,stamp)')
        self.db.commit()

    def match(self, sender, receiver, start, end):
        """Preserve per-key capture order and the original one-to-one boundary matcher."""
        arrivals_by_key = iter(receiver.items())
        sends_by_key = iter(sender.items())
        arrival = next(arrivals_by_key, None)
        total = unmatched = matched = sum_ns = 0
        context = self.next_context
        self.next_context += 1
        pending = []
        try:
            for key, stamps in sends_by_key:
                while arrival is not None and arrival[0] < key:
                    arrival = next(arrivals_by_key, None)
                arrivals = arrival[1] if arrival is not None and arrival[0] == key else []
                index = 0
                for stamp in stamps:
                    while index < len(arrivals) and arrivals[index] < stamp - 2_000_000:
                        index += 1
                    measured = start <= stamp < end
                    total += int(measured)
                    if index < len(arrivals) and arrivals[index] <= stamp + 2_000_000_000:
                        if measured:
                            delay = arrivals[index] - stamp
                            sum_ns += delay
                            matched += 1
                            pending.append((context, delay))
                            if len(pending) >= 8192:
                                self.db.executemany('INSERT INTO delays VALUES (?,?)', pending)
                                pending.clear()
                        index += 1
                    elif measured:
                        unmatched += 1
        finally:
            sends_by_key.close()
            arrivals_by_key.close()
        self.db.executemany('INSERT INTO delays VALUES (?,?)', pending)
        self.db.execute('CREATE INDEX IF NOT EXISTS delay_order ON delays (context,ns)')
        self.db.commit()
        delays = {}
        if matched:
            delays['mean'] = sum_ns / matched / 1e6
            for name, fraction in (('p50', .5), ('p95', .95), ('p99', .99)):
                offset = min(matched - 1, math.ceil(matched * fraction) - 1)
                delays[name] = self.db.execute('SELECT ns FROM delays WHERE context=? ORDER BY ns LIMIT 1 OFFSET ?', (context, offset)).fetchone()[0] / 1e6
        return {'sent': total, 'matched': total - unmatched, 'unmatched': unmatched,
                'loss_pct': 100 * unmatched / total if total else None, 'delay_ms': delays}
