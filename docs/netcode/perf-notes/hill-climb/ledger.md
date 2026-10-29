# Hill-climb ledger

One row per `scripts/quick_stress.sh` run (appended automatically). Newest at the bottom.

| date (UTC) | label | commit | bots | result | connected | tick p95 / max ms | ticks >33 ms | server CPU | bots CPU | RcvbufErr | RTT p95 ms | loss | KB/s per bot | reliable events per peer/s | ENet loss peak / RTT peak (server view) | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-29 14:04 | n200-default-buf | `fb55332` | 200 strategy | FAIL | 12/200 | 13.05 / 72.9 | 0.7% | 34% | 24% | 191857 | 298 | 0.67% | 131.8 | 346 | 15.8% / 919 | |
| 2026-10-29 14:05 | n200-rcvbuf32mb | `fb55332` | 200 strategy | FAIL | 8/200 | 16.61 / 56.0 | 0.8% | 26% | 22% | 151394 | 162 | 0.65% | 211.4 | 361 | 13.0% / 614 | |
