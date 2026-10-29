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
