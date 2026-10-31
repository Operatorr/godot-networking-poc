# Recovered June load-test reports

Recovered 2026-10-31 for [Retrieve historical load-test reports and incorporate them after the first draft](https://github.com/Operatorr/godot-networking-poc/issues/28).

## Provenance and retention

Nineteen original JSON reports were found in the ignored `rust/report_202606*.json` files on the author's computer. Byte-identical copies are in this directory's ignored `raw/` folder. [inventory.json](inventory.json) records original paths, byte counts and SHA256 hashes. Raw evidence stays local; the inventory and this summary are publishable text. Reports contain aggregate, per-bot and periodic samples, not packet captures or complete server Tick logs.

The branch `feature/performance-minmaxxing`, inspected at `13cbf61f9619681209f042da226af3d77afe6c0d`, also contains `docs/netcode/perf-notes/live-load-capacity-2026-06.md` and its HTML presentation. Both are preserved locally and hashed as historical interpretations, not independent measurements. That branch tree contains no original report JSONs. The search included ignored files in this checkout and the historical branch tree; it is not a claim to have searched every disk or backup.

The author confirms the remote bots ran on this computer against the then-current DigitalOcean server in Singapore. Five reports name `gsapi.marrowtech.app:8081`; fourteen explicitly name `127.0.0.1:8081`. The latter remain loopback tests, not Singapore measurements. The historical note describes a $7 Premium AMD 1-vCPU/1-GiB host sharing resources with the API, PostgreSQL, Redis and Sanctuary. This is contemporaneous narrative provenance; provider telemetry/configuration snapshots have not been recovered. The reports do not pin executable hashes, source revision, toolchain, server configuration or generator host utilization. The inspected branch SHA must not be substituted for a measured build SHA.

## Complete report inventory

Dates below are filename identifiers matching report UTC timestamps (not independently verified run-start times). Requested / connected / players means configured bots / aggregate connected bots / last server-reported player count. Duration is the recorded denominator, including near-zero failed starts. Tick columns are the latest server-reported rolling average/max, not whole-run statistics. BW is the harness's bidirectional KiB/s per connected bot / last server B/s per client. RTT is ENet avg/p95 in ms; loss is the rounded ENet statistic, not end-to-end application delivery loss. Zero values on failed starts mean no useful measurement.

| Report identifier | Target | Requested / connected / players | Duration s | Tick avg / max ms | BW KiB/s / B/s | RTT avg / p95 ms | Loss % | Original failed gates |
|---|---|---|---|---|---|---|---|---|
| 20260613_060119 | loopback | 2 / 2 / 2 | 2523.32 | 0.12 / 0.31 | 3.01 / 2911 | 1.5 / 2.0 | 0.0 | PASS executed gates |
| 20260615_150818 | loopback | 2 / 2 / 2 | 170.712 | 0.09 / 0.2 | 3.32 / 3046 | 2.5 / 3.0 | 0.0 | PASS executed gates |
| 20260615_171826 | loopback | 2 / 2 / 2 | 1873.63 | 0.08 / 0.21 | 3.35 / 3224 | 2.1 / 4.0 | 0.0 | PASS executed gates |
| 20260615_192559 | loopback | 2 / 2 / 2 | 83.4078 | 0.08 / 0.09 | 3.14 / 1340 | 1.5 / 2.0 | 0.0 | PASS executed gates |
| 20260616_200534 | loopback | 2 / 2 / 2 | 5346.23 | 0.07 / 0.17 | 3.43 / 3785 | 1.5 / 2.0 | 0.0 | PASS executed gates |
| 20260617_080740 | loopback | 3 / 3 / 4 | 291.828 | 0.12 / 0.41 | 3.27 / 2337 | 1.3 / 2.0 | 0.01 | PASS executed gates |
| 20260617_082028 | loopback | 3 / 3 / 3 | 682.227 | 0.18 / 0.51 | 3.58 / 3677 | 2.3 / 3.0 | 0.0 | PASS executed gates |
| 20260617_084032 | loopback | 3 / 3 / 3 | 1186.33 | 0.15 / 0.34 | 3.61 / 2467 | 1.3 / 2.0 | 0.0 | PASS executed gates |
| 20260617_085630 | loopback | 3 / 3 / 3 | 252.145 | 0.16 / 0.26 | 3.64 / 1954 | 1.3 / 2.0 | 0.01 | PASS executed gates |
| 20260617_155400 | loopback | 3 / 3 / 3 | 254.243 | 0.16 / 0.66 | 4.1 / 2954 | 1.7 / 3.0 | 0.0 | PASS executed gates |
| 20260617_162418 | loopback | 3 / 3 / 3 | 549.621 | 0.09 / 0.29 | 3.58 / 1410 | 2.3 / 3.0 | 0.0 | PASS executed gates |
| 20260617_171835 | loopback | 3 / 3 / 4 | 390.855 | 0.18 / 0.37 | 4.27 / 4106 | 1.6 / 2.0 | 0.0 | PASS executed gates |
| 20260619_154829 | loopback | 3 / 0 / 0 | 1.8125e-05 | 0.0 / 0.0 | 0.0 / 0 | 0.0 / 0.0 | 0.0 | crash_rate, server_tick_rate |
| 20260619_155434 | remote | 3 / 0 / 0 | 1.9667e-05 | 0.0 / 0.0 | 0.0 / 0 | 0.0 / 0.0 | 0.0 | crash_rate, server_tick_rate |
| 20260619_164045 | remote | 3 / 0 / 0 | 1.3042e-05 | 0.0 / 0.0 | 0.0 / 0 | 0.0 / 0.0 | 0.0 | crash_rate, server_tick_rate |
| 20260619_165458 | remote | 3 / 3 / 4 | 37.0909 | 0.14 / 0.2 | 3.61 / 2579 | 41.7 / 44.0 | 0.0 | PASS executed gates |
| 20260619_170352 | loopback | 2 / 0 / 0 | 1.50037 | 0.0 / 0.0 | 0.0 / 0 | 0.0 / 0.0 | 0.0 | crash_rate, server_tick_rate |
| 20260619_170620 | remote | 50 / 50 / 51 | 120 | 3.0 / 4.11 | 14.85 / 16211 | 44.1 / 47.0 | 0.0 | bandwidth |
| 20260619_172402 | remote | 200 / 99 / 100 | 300 | 11.7 / 17.41 | 28.84 / 26072 | 46.8 / 49.0 | 0.04 | bandwidth, crash_rate |

Every report skipped `per_peer_budget` because no rate budget was configured. Failed starts also skipped AoI when there were no observations. “PASS executed gates” preserves the old harness result; it does not certify current correctness or valid offered load.

## Reconciliation and changed conclusions

- The pasted June 13 two-bot summary matches `report_20260613_060119.json`: loopback, 2523.3227 s (2523 s rounded), 0.12/0.31 ms reported Tick, 3.01 KiB/s, 2911 server B/s, RTT 1.5/2 ms, loss 0.00%, all executed gates pass.
- The pasted June 19 fifty-bot summary matches `report_20260619_170620.json`, including 120 s, 3.00/4.11 ms, 14.85 KiB/s, 16211 B/s, RTT 44.1/47 ms, 51 players, 89 entities, 88,581,168 server bytes, 190,673 packets sent / 1,225,513 received and 50/50 within 1150 u. The bandwidth gate failed. The raw file is now recovered; these are no longer merely pasted numbers.
- `report_20260619_172402.json` adds the 300 s stress attempt: 200 requested, 99 connected, 100 server players, 101 bots with `server disconnected (reason 2)`, 11.70/17.41 ms reported Tick, 28.84 KiB/s, RTT 46.8/49 ms, loss 0.04%. There were no recorded panics, decode failures or send failures. The old note attributes the rejections to `max_players=100`; the raw report supports rejection events and counts, but carries no deployed config. The 50.5% “crash” gate is a disconnected-bot classification, not proof that half the server population crashed. This was not a successful 200-bot test.
- Five reports have zero connected bots (three loopback, two remote). Among the five remote files are those two failed starts, one successful short smoke, the baseline and the stress attempt. Failed-start zeros cannot establish low latency, zero delivery loss or low bandwidth under load.
- `rust/load_test/src/metrics.rs` on the historical branch computes bandwidth as `(sum sent + sum received) / connected / duration / 1024`. The JSON key says `kbps` and the display says `KB/s`, but the quantity is KiB/s, bidirectional application counters, not outbound wire bytes/player-second. It computes “crash rate” from disconnected/total bots and retains the latest server metrics packet. Tick statistics in that packet are over the server's rolling sample window; `total_bytes_sent` is cumulative server process accounting, not a window delta. Dividing its final value by the bot duration does not establish measured run egress. No billing/cost forecast is imported.
- The 32.9 and 34.8 Hz values are historical Tick-span estimators, not verified server rates. The branch code divides a seen Tick span by the fixed duration; unequal spawn and measurement windows can inflate it. `30 × 131.6 / 120 = 32.9` in the article is an explanatory reconstruction, not a recovered 131.6-second timing trace. The reports lack raw Tick-span endpoints for independently recomputing it.
- The historical note's assertion that a 1000-unit radius covers all pairs in a 2000-unit-square Arena is false: opposite corners are about 2828 units apart. Its two-point fit and 120–130 “clean” / 150–165 “hard” ceilings remain unvalidated projections, not capacity findings. Two terminal rolling observations, missing build/config pins and differing admitted populations cannot establish a scaling law. No comparison with CAX11 or current code is controlled.
- The note's DO CPU/load/graph observations lack recovered telemetry; claims of a provider bandwidth undercount, confirmed CPU saturation or compulsory sharding are not adopted. Raw recovery improves provenance, not the validity of those conclusions.

## Article incorporation

Article A and C2 now identify the recovered report behind the estimator example and include the qualified remote-run history. The shared appendices link this complete table and inventory; C1's industry-only narrative needs no historical results. The excluded 5 KB/s sidebar stays excluded. Existing capacity, fixed-build economics and byte-share `[MEASURE]`/`[PENDING]` boundaries remain in place. Historical projections are not added to the capacity charts: that would imply comparable builds and validated capacity that the evidence cannot support.

## Code references for interpreting the historical schema

Inspected at historical branch tip `13cbf61f9619681209f042da226af3d77afe6c0d`, not asserted to be the deployed revision:

- [Harness aggregation and serialization](https://github.com/Operatorr/godot-networking-poc/blob/13cbf61f9619681209f042da226af3d77afe6c0d/rust/load_test/src/metrics.rs): bidirectional /1024 bandwidth, connected denominator, disconnected-bot classification, latest server packet and Tick-span estimator. Recomputing bandwidth from each recovered report's per-bot counters agrees with every connected run to the report's two-decimal precision.
- [Server metrics collector](https://github.com/Operatorr/godot-networking-poc/blob/13cbf61f9619681209f042da226af3d77afe6c0d/rust/server/src/net/metrics.rs): rolling 30-sample Tick window and cumulative `total_bytes_sent`.
