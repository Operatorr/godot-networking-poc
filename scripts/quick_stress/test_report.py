#!/usr/bin/env python3
"""Fixture tests for the stress report. Run: python3 -m unittest discover scripts/quick_stress"""
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report  # noqa: E402
import sample_host  # noqa: E402

RUN = {"bots": 100, "threads": 3, "duration_s": 60, "t_swarm_start": 1000.0, "t_swarm_end": 1070.0}
CRITERIA = [{"key": k, "passed": True, "value": "ok"} for k in ("latency_avg", "latency_p95", "packet_loss", "crash_rate", "server_tick_rate")]
BOTS = {"aggregated": {"connected_bots": 100, "total_errors": 0, "latency_avg_ms": 2, "latency_p95_ms": 3, "packet_loss_pct": 0}, "success_criteria": CRITERIA}
TICKS = {"players_peak": 100.0, "peak_span_s": 62.0, "steady_span_s": 62.0, "steady": {"ticks": 1860, "over_33ms_pct": 0.0, "work_ms_p95": 8.0, "players_avg": 100.0}}
HOST = {"first_ts": 999.0, "last_ts": 1071.0, "udp_whole_run": {"RcvbufErrors": 0}, "procs": {}}


class VerdictEvidence(unittest.TestCase):
    def test_complete_zero_drop_run_passes(self):
        status, reasons, findings = report.verdict(RUN, BOTS, TICKS, None, HOST)
        self.assertEqual((status, reasons), ("PASS", []))
        self.assertIn("NO BOTTLENECK HIT", findings[0])

    def assert_incomplete(self, ticks, host, expected):
        status, reasons, findings = report.verdict(RUN, BOTS, ticks, None, host)
        self.assertEqual(status, "INCOMPLETE")
        self.assertTrue(any(expected in r for r in reasons), reasons)
        self.assertFalse(any("NO BOTTLENECK HIT" in f for f in findings), findings)

    def test_missing_tick_data_is_not_a_pass(self):
        self.assert_incomplete(None, HOST, "Tick-budget")

    def test_empty_tick_file_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ticks.csv")
            with open(path, "w") as f:
                f.write("mono_ns,authenticated\n")
            self.assertIsNone(report.analyze_ticks(path))

    def test_tick_data_covering_part_of_the_run_is_not_a_pass(self):
        self.assert_incomplete({**TICKS, "steady_span_s": 20.0}, HOST, "covers only 20 s")

    def test_dead_sampler_is_not_a_pass(self):
        self.assert_incomplete(TICKS, None, "no host samples")
        self.assert_incomplete(TICKS, {**HOST, "last_ts": 1010.0}, "stopped 60 s before")

    def test_unavailable_drop_counter_is_not_an_observed_zero(self):
        self.assert_incomplete(TICKS, {**HOST, "udp_whole_run": {}}, "drop counter unavailable")

    def test_a_real_failure_outranks_missing_telemetry(self):
        bad = {**BOTS, "aggregated": {**BOTS["aggregated"], "connected_bots": 50}}
        self.assertEqual(report.verdict(RUN, bad, None, None, None)[0], "FAIL")

    def test_peak_population_below_request_fails(self):
        status, reasons, _ = report.verdict(RUN, BOTS, {**TICKS, "players_peak": 40.0}, None, HOST)
        self.assertEqual(status, "FAIL")
        self.assertTrue(any("40/100" in r for r in reasons), reasons)

    def test_full_population_must_hold_for_the_whole_duration(self):
        status, reasons, _ = report.verdict(RUN, BOTS, {**TICKS, "peak_span_s": 30.0}, None, HOST)
        self.assertEqual(status, "FAIL")
        self.assertTrue(any("only 30 s" in r for r in reasons), reasons)

    def test_host_drop_delta_ignores_counters_missing_from_either_end(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "host.ndjson")
            with open(path, "w") as f:
                f.write(json.dumps({"ts": 1, "udp": {"snmp": {"InDatagrams": 1}}}) + "\n")
                f.write(json.dumps({"ts": 2, "udp": {"snmp": {"InDatagrams": 2, "RcvbufErrors": 5}}}) + "\n")
            self.assertNotIn("RcvbufErrors", report.analyze_host(path, 0)["udp_whole_run"])


def enet(loss, rtt):
    return {"loss_mean_pct_max": loss, "loss_max_pct_max": loss, "rtt_mean_ms_max": rtt}


class RetransmitDiagnosis(unittest.TestCase):
    def findings(self, en, host=HOST):
        return " | ".join(report.verdict(RUN, BOTS, TICKS, {"enet": en}, host)[2])

    def test_stable_high_rtt_is_latency_not_ack_loss(self):
        text = self.findings(enet(0.0, 210.0))
        self.assertIn("ELEVATED RTT", text)
        self.assertNotIn("STORM", text)
        self.assertNotIn("acks", text)

    def test_loss_without_drops_is_not_blamed_on_the_socket(self):
        text = self.findings(enet(8.0, 210.0))
        self.assertIn("ENET PACKET LOSS", text)
        self.assertNotIn("STORM", text)

    def test_corroborated_loss_is_a_storm(self):
        self.assertIn("STORM", self.findings(enet(8.0, 210.0), {**HOST, "udp_whole_run": {"RcvbufErrors": 9}}))
        self.assertIn("STORM", self.findings(enet(8.0, 40.0), {**HOST, "server_socket": {"drops": 3}}))


def server_samples(path, event_sends, reliable=None):
    phase = lambda ns: {"total_ns": ns, "count": 30, "max_ns": 1}
    zero = {p: phase(0) for p in report.PHASES}
    pct = {"world_tick": 60, "snapshot_build": 50, "service_and_route": 10, "outbox_flush": 10, "enet_flush": 5}
    full = {p: phase(int(pct[p] * 1e7)) for p in report.PHASES}  # % of a core over a 1 s window
    with open(path, "w") as f:
        for mono, phases, events, rel in ((0, zero, [0] * 16, [0] * 16), (10**9, full, event_sends, reliable)):
            row = {"boundary": "", "mono_ns": mono, "tick": 30 if mono else 0, "loop_phases": phases, "event_sends": events, "source_events": events}
            if reliable is not None:
                row["reliable_event_sends"] = rel
            f.write(json.dumps(row) + "\n")


class ServerTelemetry(unittest.TestCase):
    def analyze(self, event_sends, reliable=None):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "server.ndjson")
            server_samples(path, event_sends, reliable)
            return report.analyze_server_samples(path, 0)

    def test_phase_total_counts_snapshot_build_once(self):
        srv = self.analyze([0] * 16)
        self.assertAlmostEqual(srv["phase_core_pct_total"], 85.0)
        self.assertAlmostEqual(srv["phases"]["snapshot_build"]["core_pct"], 50.0)

    def test_cpu_bound_ranking_uses_disjoint_phases(self):
        srv = {**self.analyze([0] * 16), "process": {"cpu_core_pct": 90.0}}
        text = " | ".join(report.verdict(RUN, BOTS, TICKS, srv, HOST)[2])
        self.assertIn("snapshot_build 50%", text)
        self.assertNotIn("world_tick", text)

    def test_reliable_and_unreliable_fire_events_are_reported_separately(self):
        sends = [0] * 16
        reliable = [0] * 16
        sends[12] = 2  # one player shot (unreliable) + one monster shot (reliable)
        reliable[12] = 1
        srv = self.analyze(sends, reliable)
        self.assertEqual(srv["event_sends_per_s"]["PROJECTILE_FIRED"], 2.0)
        self.assertEqual(srv["reliable_event_sends_per_s"]["PROJECTILE_FIRED"], 1.0)
        summary = report.summary_line(RUN, "PASS", {}, {"players_avg": 1.0}, srv, None, None)
        self.assertEqual(summary["reliable_events_per_peer_s"], 1.0)
        self.assertEqual(summary["all_events_per_peer_s"], 2.0)

    def test_telemetry_without_the_reliable_counter_reports_it_unknown(self):
        sends = [0] * 16
        sends[12] = 2
        srv = self.analyze(sends)
        self.assertIsNone(srv["reliable_event_sends_per_s"])
        summary = report.summary_line(RUN, "PASS", {}, {"players_avg": 1.0}, srv, None, None)
        self.assertIsNone(summary["reliable_events_per_peer_s"])
        self.assertIn("delivery is unknown", report.render("run", RUN, BOTS, None, srv, HOST, {})[3])


class SocketQueues(unittest.TestCase):
    def test_proc_net_udp_queue_column_is_tx_then_rx(self):
        udp = ("  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode ref pointer drops\n"
               "  1: 00000000:1F91 00000000:0000 07 00000080:00000010 00:00000000 00000000 0 0 1 2 0 7\n")

        def fake_open(path, *a, **k):
            if path == "/proc/net/udp":
                return io.StringIO(udp)
            raise OSError(path)

        with mock.patch("builtins.open", fake_open):
            socket = sample_host.udp_linux(8081)["socket"]
        self.assertEqual(socket, {"tx_queue": 128, "rx_queue": 16, "drops": 7})


if __name__ == "__main__":
    unittest.main()
