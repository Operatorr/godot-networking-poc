# Hill-climb ledger

One row per `scripts/quick_stress.sh` run (appended automatically). Newest at the bottom.

| date (UTC) | label | commit | bots | result | connected | tick p95 / max ms | ticks >33 ms | server CPU | bots CPU | RcvbufErr | RTT p95 ms | loss | KB/s per bot | reliable events per peer/s | ENet loss peak / RTT peak (server view) | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-29 13:54 | harness-check | `117d640` | 50 strategy | FAIL | 50/50 | 3.94 / 91.2 | 0.1% | 13% | 19% | 0 | 5 | 0.01% | 19.2 | 158 | n/a / n/a | |
| 2026-10-29 13:56 | ladder-100 | `117d640` | 100 strategy | FAIL | 100/100 | 11.45 / 19.5 | 0.0% | 30% | 35% | 0 | 3 | 0.02% | 31.8 | 390 | n/a / n/a | |
| 2026-10-29 13:57 | ladder-150 | `117d640` | 150 strategy | FAIL | 150/150 | 22.47 / 44.7 | 0.2% | 56% | 54% | 1117 | 8 | 0.07% | 42.3 | 671 | n/a / n/a | |
| 2026-10-29 13:58 | ladder-200 | `117d640` | 200 strategy | FAIL | 12/200 | 20.95 / 55.7 | 0.7% | 36% | 25% | 193549 | 217 | 0.69% | 165.3 | 437 | n/a / n/a | |
| 2026-10-29 14:02 | n200-default-buf | `fb55332` | 200 strategy | FAIL | 12/200 | 13.05 / 72.9 | 0.7% | 34% | 24% | 191857 | 298 | 0.67% | 131.8 | 346 | 15.8% / 919 | |
| 2026-10-29 14:04 | n200-rcvbuf32mb | `fb55332` | 200 strategy | FAIL | 8/200 | 16.61 / 56.0 | 0.8% | 26% | 22% | 151394 | 162 | 0.65% | 211.4 | 361 | 13.0% / 614 | |
| 2026-10-29 14:06 | n200-buf16mb | `b80c500` | 200 strategy | FAIL | 200/200 | 30.83 / 115.2 | 3.7% | 98% | 56% | 108977 | 1855 | 0.39% | 23.5 | 476 | 23.2% / 5661 | |
| 2026-10-29 14:08 | n200-movement | `b80c500` | 200 movement | FAIL | 200/200 | 14.53 / 56.6 | 0.2% | 37% | 35% | 45 | 5 | 0.03% | 18.5 | 2 | 0.0% / 4 | |
| 2026-10-30 04:56 | changeA-100 | `80146b0` | 100 strategy | PASS | 100/100 | 8.66 / 18.2 | 0.0% | 22% | 23% | 0 | 3 | 0.02% | 29.4 | 154 | 0.0% / 4 | |
| 2026-10-30 04:57 | changeA-150 | `98a6304` | 150 strategy | PASS | 150/150 | 15.83 / 23.4 | 0.0% | 38% | 33% | 0 | 3 | 0.03% | 37.4 | 252 | 0.0% / 2 | |
| 2026-10-30 04:58 | changeA-200 | `3af68df` | 200 strategy | FAIL | 200/200 | 25.91 / 39.9 | 0.7% | 58% | 46% | 178 | 8 | 0.08% | 45.0 | 393 | 0.0% / 9 | |
| 2026-11-02 06:05 | cax11-changeA-200-mac | `0c9ecaf` | 200 strategy | FAIL | 200/200 full 60 s | 27.65 / 59.24 | 0.167% | 78.6% | 54.4% | 5656 whole run | 221 | 0.05% | 46.23 | unavailable (mixed delivery counters) | 0.553% mean / 234 worst-peer ms | CAX11 server + Mac M4 bots; socket drops 5656; [evidence](cax11-changeA-200-20261102.md); RTT/loss aggregates include ramp; inner minute sampled drops 2606 |
