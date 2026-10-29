# Hill-climb ledger

One row per `scripts/quick_stress.sh` run (appended automatically). Newest at the bottom.

| date (UTC) | label | commit | bots | result | connected | tick p95 / max ms | ticks >33 ms | server CPU | bots CPU | RcvbufErr | RTT p95 ms | loss | KB/s per bot | reliable events per peer/s | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-29 13:57 | ladder-100 | `117d640` | 100 strategy | FAIL | 100/100 | 11.45 / 19.5 | 0.0% | 30% | 35% | 0 | 3 | 0.02% | 31.8 | 390 | |
| 2026-10-29 13:58 | ladder-150 | `117d640` | 150 strategy | FAIL | 150/150 | 22.47 / 44.7 | 0.2% | 56% | 54% | 1117 | 8 | 0.07% | 42.3 | 671 | |
| 2026-10-29 13:59 | ladder-200 | `117d640` | 200 strategy | FAIL | 12/200 | 20.95 / 55.7 | 0.7% | 36% | 25% | 193549 | 217 | 0.69% | 165.3 | 437 | |
