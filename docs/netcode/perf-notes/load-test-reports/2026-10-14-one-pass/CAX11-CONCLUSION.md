# CAX11 checkpoint: observed failure and hypotheses

The frozen Omega Realm build on the tested CAX11 game/bot pair failed all five requested Strategy overload ramps. The exact retained Tick population peaks were **176–191 authenticated players**; connection/authentication timeouts stopped further joins. Game-process CPU subsequently approached **one logical CPU's budget**. These are observed startup failures for this build, workload, configuration and host pair.

For the article: **“Our CAX11 Strategy join ramps broke around 180–190 authenticated players, with UDP receive-buffer errors and game-process CPU approaching one core.”** The peak is not a maintained five-minute population. Strategy 100 remains the highest passing native rung; Strategy 125/150 already failed offered-load validation. Movement, Combat and Clustered have their own outcomes in the [lower-ladder checkpoint](PRE-STRATEGY-EXTENSION.md). A general claim that every CAX11 server supports 190 players is not established.

## What failed first

The retained one-second host counters expose UDP receive-buffer errors before the later near-core CPU episodes. The table gives the **population range during the first interval containing a positive error delta**, not the exact population or time of the first discarded datagram. CPU is the game-process average over that same interval, with 100% equal to one logical CPU.

| Requested Strategy players | Population during first game-host receive-buffer errors | Game CPU in that interval | Error increment | Peak authenticated population before abort |
| ---: | ---: | ---: | ---: | ---: |
| 200 | 131–139 | 56.80% | 5 | 191 |
| 250 | 157–164 | 69.04% | 14 | 185 |
| 500 | 156–162 | 76.18% | 380 | 176 |
| 750 | 132–140 | 58.12% | 135 | 180 |
| 999 | 150–157 | 64.06% | 123 | 190 |

[Reproducible onset points](strategy-failure-onset.json) are derived from `game/host.ndjson.gz` and the per-Tick authenticated field in `game/ticks.csv.gz` by `scripts/load_campaign/strategy_extension_report.py`. The Linux UDP enqueue path associates receive-buffer errors with failed receive queueing, including socket receive-buffer pressure. These are host-wide counters; the isolated game-flow observations support association with the test, but they are not per-socket drop traces. [Linux UDP implementation](https://github.com/torvalds/linux/blob/master/net/ipv4/udp.c).

The boot records show a 262,144-byte requested and 524,288-byte effective game socket receive buffer. The tested correction already applies ENet's requested buffers; this is not evidence of the earlier ignored-buffer-option bug returning. Linux doubles the receive-buffer request to account for bookkeeping overhead; the effective value is not all available packet payload space. [Linux socket API](https://man7.org/linux/man-pages/man7/socket.7.html). Source: each retained `boot.log`, and `rust/server/src/net/transport.rs` at game revision `b1266c1`.

The observed sequence is **receive-buffer errors → later near-core process CPU and lost players → join timeout and controller abort**. CPU is sampled at about one second; a shorter processing stall or packet burst can overflow a queue while that second's average CPU is below 100%. The exact order within a sample interval, the CPU hot path and the role of retransmissions are not measured. The server process remained available for cleanup; “failure” here means failure to establish/maintain offered load, not a proven process crash.

## Hypotheses for the later CCX13 comparison

| Hypothesis | Current support and limitation | Prediction / evidence to compare on CCX13 |
| --- | --- | --- |
| Serial game-loop processing runs out of time | ENet servicing and authoritative Ticks share the main loop; process CPU approaches one core and some ramp Ticks exceed 33.33 ms. There is no Tick-thread or function-level CPU profile. | At matched actual populations and valid input cadence, faster processing should reduce Tick work and delay overload. Collect main-loop phase timings or a bounded profile to distinguish simulation, replication/encoding and ENet processing. |
| Packet bursts and gaps between socket reads overflow the receive queue | Drops begin while one-second CPU is 57–76%. The loop drains ENet events between Ticks; finite socket buffers cannot absorb arbitrary bursts. The actual service-gap distribution was not collected. | Compare first-drop population, burst packet rate, effective buffers and socket-drain gaps. If drops persist at similar populations while CPU/Tick work falls, inspect buffering, service scheduling and reliable traffic. Any buffer/stagger change is a separately identified diagnostic cell. |
| Loss and reliable traffic amplify processing/backlog | Large UDP error totals and declining populations accompany timeout; reliable retries are retained as one-second flow points. No controlled intervention establishes whether retries cause or follow overload. | Align retries/ACK traffic, backlog and error onset. A similar failure at lower CPU would strengthen a transport/protocol hypothesis; a different failure count alone does not prove one. |
| Generator I/O/cadence contributes | Ramp bot CPU peaks are about 81–87%, but both hosts drop UDP. Most aborted ramps have no cumulative bot observation, so valid offered cadence cannot be claimed. Strategy 150 separately reached near-core generator CPU and missed offered load. | Retain the same bot host for matching lower cells, verify per-bot self/wire cadence and actual population, and monitor its CPU/UDP drops. If it limits a higher cell, report that limit before attributing capacity to the game host. |

The later comparison must preserve code revision, release-build settings, region, workload, Class mix, bot seed/input rate/stagger, Tick/Snapshot rates, AoI and bandwidth budgets. Record each architecture's executable hash and compiler, effective socket buffers, kernel, CPU/steal, population, per-bot cadence, Tick work, UDP errors and retry/delivery points. The server uses an entropy-seeded world RNG, so the retained bot seed does not make entity histories identical; compare actual entity counts as well. CAX11 versus CCX13 changes architecture, CPU allocation and hardware together. It is a practical host comparison, not a controlled test of only dedicated versus shared CPU. No host is purchased or provisioned by this checkpoint.

The [later CCX13 task](https://github.com/Operatorr/godot-networking-poc/issues/34) retains its existing readiness gate. Equal failure populations would be an observation to explain, not proof of equal bottlenecks. A valid five-minute offered-load window is still needed for any sustainable-capacity claim or 999-derived 1000-CCU forecast.

## Operator closure of this execution ticket

On 2026-10-14, the operator accepted the CAX11 checkpoint and requested that the committed work be merged into `master` and **Execute the revised one-pass CAX11 load-test matrix** be closed. This explicitly ends that execution ticket at the recorded, failure-truncated checkpoint; it does not assert that the originally planned full matrix completed.

Completed evidence includes lower-ladder passes/failures and refinements, idle controls, compact collector validation, CPU reports, the native Combat 100 network control and one delay25 Combat 100 observation, plus the five individually delegated Strategy overload attempts. Original failed/invalid observations and replacement identities remain preserved. [Extension audit](strategy-extension-audit.json), [ledger](strategy-extension-ledger.json) and [final cleanup](strategy-extension-final-cleanup.json) verify the new attempts and host restoration.

The remaining delay/jitter/loss groups and control positions, Snapshot15/AoI600 transfer comparisons, genuinely external-client accounting, complete required-case/source/archive audit and final article transfer/cost synthesis remain with **[Run the new load tests and record results](https://github.com/Operatorr/godot-networking-poc/issues/31)**. That issue stays open. Admission testing at 999+1 and a 1000-CCU forecast are ineligible because Strategy 999 did not pass. The original campaign state is not rewritten to mark unfinished phases complete.
