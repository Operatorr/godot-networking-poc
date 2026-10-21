# Strategy 200 UDP baseline reproduction — 2026-10-21

**Outcome: reproduced; failed ramp, diagnostic only.** Exactly one Strategy 200 swarm ran for 38.051319474 seconds before the remote guard terminated it on `Bot 190 failed to connect: connect timeout` (2026-10-21 11:45:41.509217 UTC). The retained per-Tick peak was **189 authenticated / 129 living players**; these are separate maxima. Authentication had fallen to 111 at the last Tick before termination. Phase 2 never began, so there is no steady window or capacity pass. Strategy 100 remains the prior validated native rung; this observation establishes no new sustained limit.

Work is scoped to [Diagnose UDP receive-buffer errors and increase validated CAX11 capacity](https://github.com/Operatorr/godot-networking-poc/issues/38). The original [one-pass checkpoint](../2026-10-14-one-pass/CAX11-CONCLUSION.md) and its campaign state were preserved. This run agent performed no second experiment, code/transport tuning, commit, issue closure, or further delegation.

## Socket attribution and exact counters

The fresh game socket belonged to `omega-server`, PID **558927**, fd **7**, inode **2046966**. Its `ss` drop counter started at **0** and ended at **172927**, exactly matching the game-host `Udp:RcvbufErrors` delta. Effective receive/send limits were **524288 / 524288 bytes**; boot logging confirmed ENet requested **262144 / 262144 bytes**. The previous idle socket had 182585 historical drops and was not used for this comparison.

The generator process was `omega-load-test`, PID **605519**. Across 190 observed socket inodes, 18 showed nonzero receive drops. Summing each inode’s maximum observed `ss` drop counter yields **3745**, a lower bound against **4178** host-wide receive-buffer errors: **433 remain unattributed by the sampled socket evidence**. Bot sockets had effective receive/send limits **212992 / 212992 bytes**. The watchdog terminated the generator before the final socket snapshot, so its sockets were already gone. Do not equate the lower bound to an exact process-wide total.

| Counter delta | Game host | Bot host |
| --- | ---: | ---: |
| `Udp:InDatagrams` | 244736 | 325074 |
| `Udp:OutDatagrams` | 344991 | 417663 |
| `Udp:InErrors` | 172927 | 4178 |
| `Udp:RcvbufErrors` | 172927 | 4178 |
| `Udp:SndbufErrors` | 131 | 0 |
| `Udp:InCsumErrors` | 0 | 0 |
| `Udp:NoPorts` | 0 | 12272 |
| `Udp:IgnoredMulti` | 0 | 0 |
| `Udp:MemErrors` | 0 | 0 |
| Interface RX drops | 0 | 0 |
| Interface TX drops | 0 | 0 |
| Native fq_codel drops / overlimits | 0 / 0 | 0 / 0 |
| fq_codel requeues | 115 | 119 |

Game host counters cover **2026-10-21T11:44:58.169235+00:00 → 2026-10-21T11:45:45.177752+00:00**, 47.008517953 seconds. Bot counters cover **2026-10-21T11:44:58.718755+00:00 → 2026-10-21T11:46:36.733955+00:00**, 98.015200134 seconds, including extra idle collection during cleanup. These are explicitly different host observation windows, not a matched steady comparison. The bot `NoPorts` count includes termination/cleanup; it is not proof of application decode failure. Game send-buffer errors are host-wide and are not attributed to a particular send call.

First game receive-buffer errors occurred in the sampled interval **2026-10-21T11:45:22.173055+00:00 → 2026-10-21T11:45:23.173197+00:00**: **420** errors, **163–169 authenticated players**, and **80.988494%** game-process CPU (100% = one logical CPU). The adjacent socket sample recorded the same 420 drops with 125760 bytes of receive memory. Maximum sampled game receive memory was **524112 bytes**, against a 524288-byte limit; maximum sampled `Recv-Q` was **524000 bytes**. `ss` columns and memory counters are read at slightly different instants.

First bot receive-buffer errors occurred in **2026-10-21T11:45:33.723274+00:00 → 2026-10-21T11:45:34.723453+00:00**: **45** errors, with **172 authenticated players** on the game host. Bot socket inodes **2237698** and **2237701**, both owned by PID 605519, recorded **3 / 42** drops and **212368 / 212944** bytes of receive memory. Maximum sampled bot receive memory was **212960 bytes**, against a 212992-byte limit.

One-second samples bracket the onset; they do not identify the first discarded packet, peak subsecond occupancy, or ENet read-gap distribution. Both endpoints had zero `ss` command failures. Raw `/proc/net/udp` and `/proc/net/udp6` were also retained privately.

## CPU, Tick work, population and bounded logs

CPU below covers only retained host intervals within swarm launch/termination: **38.005773712 s game**, **37.004721818 s bots**. All process percentages use one logical CPU as 100%; each host has two logical CPUs.

| Observation | Game | Bots |
| --- | ---: | ---: |
| Process CPU mean | 64.753319% | 51.993365% |
| Process CPU 1 Hz peak | 99.991561% | 80.988747% |
| Host executing CPU mean, two-core capacity | 41.420278% | 29.669570% |
| Host executing CPU 1 Hz peak, two-core capacity | 64.646465% | 45.876289% |
| CPU steal | 0% | 0% |

The game process spent **15.002079699 s** of retained intervals at ≥95% of one CPU. Generator-unit CPU, including the small watchdog, averaged **52.102059%** and peaked at **80.683889%**. These are process/host averages, not profiles or proof of a particular hot path.

Retained **1505 Ticks**, of which **1151** are within launch/termination timestamps. Active mean Tick work **12.994256844 ms**, maximum **35.926252 ms**; **10** Ticks exceeded 33.333333 ms. Maximum accumulator lag **0.788944056 s**. Peak pending replication **6889**, maximum deferred wait **9 Ticks**. These diagnostics do not measure every ENet service gap or the whole main loop.

The final cumulative application samples report **0 decode errors**, **0 measured send errors**, **2069 Baselines**, and **152760 delta Snapshots**. Zero application send errors does not negate the separately observed 131 kernel `SndbufErrors`.

The retained game-log tail is capped at **4000 lines** (682459 bytes after ANSI removal): **3907 oversized-unreliable warnings**, all on channel 0, payload lengths **1201–1356 bytes**, plus 93 disconnect lines. This is a bounded tail, not the full-run warning count. Bot log: **23 lines**, one connect-timeout line; no retained decode/panic/OOM text. Bounded kernel journals for the experiment returned no entries on either host. There was no service restart during the run. Warnings and timeout are observations, not established causes.

`ramp_input_cadence = null`; `generator_valid = null`. The frozen bot measurement file is **0 bytes**, and there is no `phase.json`. Actual per-bot offered/wire cadence, reliable retry/ACK timelines, packet burst shape, queue residence time and phase-specific CPU costs remain unknown. No successful offered-load validation is claimed.

## Exact experiment provenance

Game revision `b1266c1d53a589c33b5ae8b5259bc7b2968dd252`; executable `/home/deploy/omega-stabilized-b1266c1/rust/target/release/omega-server`:

```text
f2bf76c6fa3c28b7fb9b5d52f216061e9c3239999d67bf8a42acadf44dada3a2
```

Bot revision `642c1472232a5d3681654ab2965ba09db12ad69d`; executable `/home/deploy/omega-measured/rust/target/release/omega-load-test`:

```text
8af491831304e1ab913089e3b8f1750ea701e4ccd8993d834bcc30ecfa3e8bdf
```

Both were existing frozen release artifacts; no rebuild. Recorded toolchain: `rustc 1.95.0 (59807616e 2026-04-14)`, LLVM 22.1.2, `cargo 1.95.0 (f2d3ce0bd 2026-03-21)`, target `aarch64-unknown-linux-gnu`. Both hosts: Neoverse-N1, two logical CPUs, kernel `7.0.0-30-generic` / `#30-Ubuntu SMP PREEMPT_DYNAMIC`. Toolchain inspection does not independently attest every historical compiler flag.

Controller invocation:

```sh
python3 scripts/load_campaign/udp_baseline.py run
```

Exact workload command, with the connection address deliberately replaced:

```sh
env -u OMEGA_TICKET_API -u OMEGA_LOAD_TEST_SECRET \
  OMEGA_MEASURE_DIR=/home/deploy/omega-results/udp-diagnosis-20261021/bots \
  /home/deploy/omega-measured/rust/target/release/omega-load-test \
  --server <game-host>:8081 --bots 200 --behavior strategy --duration 120 \
  --input-hz 30 --seed 30 --stagger 100 --difficulty 1.0 \
  --bandwidth-budget 0 --assertions strict --aoi-exit-radius 1100 \
  --output /home/deploy/omega-results/udp-diagnosis-20261021/bots/bot.json
```

The remote Python watchdog executed this argv with the shown environment, under systemd unit `omega-udp-diagnosis-20261021-swarm`, user `deploy`, `LimitNOFILE=8192`, `RuntimeMaxSec=305`, `TimeoutStopSec=10`, `KillMode=mixed`. It checked join failures every 0.5 s. Ramp cap **180 s**, post-ramp cap **120 s**; local population-collapse gate was two successive polls below 65% of a peak ≥100. The first join failure ended this run before those caps. A 420-second game-service restoration timer was installed and later stopped.

Game command remained `omega-server --config /etc/omega-loadtest/arena.json --allow-unsigned-tickets` with the pinned executable above. The JSON config was unchanged, SHA-256 `bac0bf8947937a334b4fd9e814e1e3a4e15b9753fd3f1c02e185285d26f0d68c`:

```json
{
  "mode": "arena",
  "port": 8081,
  "metrics_port": 9100,
  "tick_rate": 30,
  "max_players": 999,
  "region": "local",
  "advertise_url": "",
  "debug_logging": false,
  "api_server_url": "",
  "allow_unsigned_tickets": true,
  "aoi_radius": 1000.0,
  "aoi_exit_radius": 1100.0,
  "lod_near_radius": 400.0,
  "lod_mid_radius": 1000.0,
  "snapshot_rate_hz": 30,
  "default_client_bandwidth_bps": 120000,
  "max_client_bandwidth_bps": 200000,
  "monster_ai_difficulty": 0.85
}
```

Only measurement output was temporarily redirected to the new namespace with a runtime systemd drop-in; no game, transport, socket, firewall, qdisc, API or persistence settings were tuned. Native fq_codel and existing offloads were retained. The bot Class mix is the frozen binary’s default Warrior/Rogue/Mage rotation. Bot seed 30 does not fix the entropy-seeded server world.

## Collection and limits

Both hosts ran the existing `host_collect.sample` plus **`ss -u -a -m -n -p -e`**, `/proc/net/udp`, and `/proc/net/udp6` at a bounded **1 Hz**, for at most **350 s**. Existing per-Tick and server cumulative measurement was enabled in the frozen game binary. No packet captures, mirror interfaces, nft measurement rules, performance profiler or kernel trace was installed. Host collector attempts to query the absent `omega_measure` nft table returned the expected absence; no flow-counter claim is made.

Collector CPU consumption measured from self/child resource counters across each full collector window was **1.138477% + 2.832399% = 3.970876% of one CPU on game**, and **1.077969% + 3.009773% = 4.087741% on bots**. Sampling elapsed time averaged **43.819943 / 43.049717 ms**, maxima **56.826659 / 55.001061 ms**, game/bots respectively. Those windows include idle time, especially the bot cleanup tail. Existing Tick observer timing averaged **29.141531 µs**, maximum **217.683 µs**; that narrow counter does not cover all measurement I/O.

**Perturbation of workload performance remains unknown:** no matched observer-off comparison was authorized or run. Measured collector resource use is not a causal overhead estimate. The previous campaign used different packet collectors. Threshold differences from October 14 cannot be assigned to a code change, hardware improvement, or precise capacity variance.

## Preservation, cleanup and evidence

Read-only preflight verified pinned hashes, native config/network, no active swarm/collector/compiler, zero game population, no API/persistence, and idle update jobs. Available remote disk was **17381621760 bytes game / 25203458048 bytes bots**. Update timers were active/enabled with their next runs many hours away and were left untouched.

The service was stopped before copying its old **2.7 GiB** measurement directory into `/home/deploy/omega-results/udp-diagnosis-20261021/original/measurement-current`. The copy was verified against source SHA-256 values before restart. Original executables, config and measurement drop-in were also copied under `original/`; original executable paths were not overwritten. On restoration the normal service resumed writing its usual current measurement directory; its pre-run contents remain in the verified backup. No remote evidence was deleted.

The game service was restored active with zero players, original config and unit text, and no runtime diagnostic override. Native qdisc configuration, filters, firewall rules and closed remote campaign state hashes matched preflight. Both apt timers remained active/enabled and update services inactive. The temporary restoration timer, swarm and both collectors were verified inactive. Final process verification found only the ordinary game server on game and no swarm/collector/trace on bots.

Cleanup caveat: the completed transient swarm unit had already unloaded. Its initial stop command returned “Unit … not loaded,” which skipped the bot collector stop in that cleanup block. The collector was explicitly stopped afterward; this explains the 99 bot samples versus 48 game samples. The final bot archive was recaptured and checksum-verified as `bots-final.tar.gz`; the earlier `bots.tar.gz` remains preserved as an incomplete-collection snapshot. The controller now accepts this already-inactive transient-unit case. No experiment was repeated to test that cleanup edit.

Private local evidence root: `deployment/hetzner/results/udp-diagnosis-20261021/`. Corresponding remote root: `/home/deploy/omega-results/udp-diagnosis-20261021/`. Raw host/process/socket/connection details stay in these private namespaces. Key files: `manifest.json`, `commands.ndjson`, preflight snapshots, `preserved-measurement-sha256.txt`, `boot.log`, `*-kernel.log`, `analysis.json`, `cleanup.json`, `final-verification-summary.json`, and the endpoint archives. `analysis.json` retains exact start/end counters, socket IDs, onset intervals, CPU statistics and Tick summaries.

| Private artifact | SHA-256 |
| --- | --- |
| `game.tar.gz` | `e318b27876da5f60ad623162ba046e93c54c2a1f8d932f51aebe5a56d454c838` |
| `bots-final.tar.gz` | `43af964645432973d162bdc2aab4b82364ee8285b877469e34504f45dd99e42d` |
| `bots.tar.gz` | `0d8282d42d1508b0a3b565cfc46f821a6de224d1828732d4dacb6f1cf046d418` |
| `udp_baseline.executed.py` | `1c240ae737704bba05f517a867361bc4dee6039392641a398440abcfdc5e9ccf` |
| `manifest.json` | `426f8f8612485c44507c5619059b9eeb6df868c61f94c41daca52851957846db` |
| `cleanup.json` | `7748194177e952ff9c29201bcf7749bd390f538b63bca7b7dc132cdf50b779d2` |
| `preserved-measurement-sha256.txt` | `f4439b76cf37faf957e1f9574a5654df36490ad9d850fd7686e1b4fcd6375a15` |

Executed controller source is retained privately as `udp_baseline.executed.py`; the manifest hash above binds that pre-cleanup-fix version. Existing `host_collect.py` SHA-256: `634fbdf22298c5bb7d86fa1e42536132dad733c0b39d0766a09aaaecb9895b43`. Both final endpoint archive hashes were checked against remote SHA-256 before local acceptance; remote originals and bundles remain intact.

## Interpretation for the parent

This run locates the complete game-host receive-buffer error delta on the authoritative game socket, and directly observes receive-queue drops on generator sockets too. Near-full sampled queue memory supports receive-buffer pressure as the immediate loss mechanism. Zero measured interface/qdisc/checksum deltas separate that observation from those error classes. Game errors appear before bot errors and before the later sustained near-core CPU interval, but 1 Hz timing cannot establish the detailed causal chain.

The causes of the processing gap remain unresolved: main-loop serialization, read scheduling, synchronized traffic, reliable feedback, replication volume, generator polling and warning/collector overhead are still competing explanations. No intervention was performed. Missing ramp cadence prevents a generator-validity or sustainable-capacity conclusion; all next experiments remain with the parent.

Final cleanup was verified at **2026-10-21 11:50:14.614377 UTC**. Local validation passed Python compilation, whitespace checks, report address-redaction checks, archive-hash comparisons and cleanup assertions. Final controller SHA-256 (cleanup handling and sanitized timeout errors corrected after the experiment): `0f4492daec7efc389cae48597d42f3a17a3b4736dbae57315fb608212c678e3e`. Rust sources were unchanged; no Rust rebuild or workspace test run was needed for this experiment.
