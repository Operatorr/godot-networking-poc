# Strategy 200 frozen-build CPU profile — 2026-10-21

**One workload run completed; failed ramp, diagnostic only.** The sampler prerequisite was provisioned and validated on both hosts. Strategy 200 ran **43.054512 s**, reaching **185 authenticated / 124 living players** (separate per-Tick maxima), before a join timeout and population collapse ended it. No Phase 2 or sustained-capacity result exists. Strategy 100 remains the prior validated native rung. The earlier blocked, read-only preflight is preserved verbatim as history below.

The strongest new finding is a shift from replication-heavy work before game receive-buffer drop onset toward **ENet reliable-command removal** during collapse. This narrows the investigation; it does not prove retransmission feedback or a specific ENet read-gap mechanism. [Compact sanitized evidence](profile-summary.json) accompanies this report; [the baseline](baseline-reproduction.md) remains unchanged.

## Experiment result and alignment

Actual bot exec release: **12:06:24.543786 UTC**; watchdog end: **12:07:07.598568 UTC**. Bot 186 logged a connect timeout at **12:07:07.174843 UTC**. The remote watchdog recorded `join-failure`. Independently, the local controller reached its two-poll population-collapse gate, `authenticated-population-below-65-percent-peak`, and began cleanup. Both signals occurred at the end of the same run; the controller's polled peak was 184 versus the per-Tick peak of 185. The last active Tick had 54 authenticated players. There was no second workload launch.

| Observation | Game | Generator |
| --- | ---: | ---: |
| Host UDP `RcvbufErrors` delta | 181843 | 3491 |
| Maximum observed socket drops, summed by inode | 181843, exact game attribution | 3416, lower bound; 75 unattributed |
| Host UDP `SndbufErrors` delta | 248 | 0 |
| Effective socket receive limit | 524288 B | 212992 B |
| Maximum sampled receive memory | 524144 B | 212976 B |
| Interface RX/TX drops | 0 / 0 | 0 / 0 |
| Native fq_codel drops / overlimits | 0 / 0 | 0 / 0 |
| Process CPU mean over retained active intervals | 70.3443% | 51.9218% |
| One-second process CPU maximum | 100.9890% | 76.9914% |

CPU uses one logical CPU as 100%; each host has two CPUs. Game process CPU covers all threads, so a one-second observation can slightly exceed 100%. Game had **18.0029 s** at ≥95% of one CPU; both hosts reported zero steal. Host counter windows include setup/cleanup: game **57.010069 s**, generator **52.007070 s**; they are not identical workload windows. Generator `NoPorts=2740` includes shutdown. The final generator socket snapshot was empty after exit, so its sampled socket total is a lower bound. Both collectors had zero `ss` failures.

The game socket was PID **568568**, fd **7**, inode **2072305**, starting with zero drops. Its final **181843** drops exactly match the host receive-error delta. The frozen generator ran as PID **615301**. Both effective receive limits remained unchanged.

Game drop onset is bracketed by **12:06:42.282734–12:06:43.282893 UTC** (17.739–18.739 s after exec), with **27** new errors, **155–162 authenticated players**, and **75.9879%** process CPU over that interval. Generator onset is **12:06:53.889738–12:06:54.889832 UTC** (29.346–30.346 s), with **70** new errors and **181–184 authenticated players**. This retains the baseline's ordering: game drops precede generator drops. A one-second bracket does not resolve first-packet time or subsecond queue occupancy.

Retained **1779 Ticks**, **1291** during the workload: mean work **12.985763 ms**, maximum **46.281155 ms**, **11** above 33.333333 ms. Maximum accumulator lag **0.724183 s**, pending replication **5650**, deferred wait **8 Ticks**. Final application cumulative observations: decode errors **0**, measured send errors **0**, Baselines **2134**, delta Snapshots **158966**. These counters do not negate kernel send-buffer errors or measure every transport-service gap.

## Top symbols and change around onset

Percentages below weight samples by their recorded CPU-clock period. “Self” means the sampled leaf instruction; “inclusive” counts any stack containing the function. Inclusive rows overlap and must not be added.

The before/after comparison deliberately excludes the uncertain onset bracket. Windows are **12:06:32.282734–12:06:42.282734**, **12:06:43.282893–12:06:53.282893**, and the final ten workload seconds **12:06:57.598568–12:07:07.598568 UTC**.

| Game path | Before onset, 10 s | After onset, 10 s | Final 10 s |
| --- | ---: | ---: | ---: |
| Samples | 462 | 929 | 914 |
| `enet_protocol_remove_sent_reliable_command`, self | 1.73% | 11.95% | 52.63% |
| Same function, inclusive | 5.84% | 15.93% | 58.53% |
| `enet_host_service`, inclusive | 20.13% | 31.97% | 68.27% |
| `BroadcastService::broadcast_state_updates`, self | 19.05% | 16.90% | 7.88% |
| Same broadcast function, inclusive | 50.65% | 44.35% | 20.13% |

Broadcast's smaller share immediately after onset is **not a reduction in absolute CPU cost**: its inclusive sampled CPU time rises **2.364 → 4.162 CPU-seconds** across those equal ten-second windows. Reliable-command removal's self time rises **0.0808 → 1.1212 → 4.8586 CPU-seconds**. In one-second slices late in collapse, its self share reaches about **68%**; these small slices are descriptive, not repeated estimates.

Across all **2930 workload game samples**, top self costs are reliable-command removal **23.99%**, broadcast state updates **13.72%**, Snapshot encoding **4.74%**, ENet outgoing commands **4.64%**, and kernel `handle_softirqs` **4.27%**; unresolved leaf symbols account for **8.81%**. Important observed call chains, written caller → callee:

- `omega_server::main → enet_host_service → enet_protocol_remove_sent_reliable_command` (**23.99% self** at the last function).
- `omega_server::main → World::tick → BroadcastService::broadcast_state_updates` (**13.72% self**, **37.17% inclusive** at broadcast).
- `omega_server::main → flush_outbox → ServerPacket::encode → Snapshot::encode_body` (**4.74% self** at encoding).

The pinned `rusty_enet 0.4.0` source shows reliable-command removal scanning sent commands, falling back to outgoing lists, and removing/freeing a matching command; acknowledgement handling calls it. This makes ACK-associated queue work a specific follow-up target. The profile does **not** reveal queue lengths, scan counts, duplicate ACKs, or retry rates, and cannot separate those explanations. [Versioned upstream source](https://raw.githubusercontent.com/jabuwu/rusty_enet/e648f4cb65d169b599e7f4807aefca40a42d7665/src/c/protocol.rs).

Generator top self costs across **2177 samples**: `Bot::poll` **13.92%**, `RawIterRange::fold_impl` **10.47%**, kernel virtio `vp_notify` **7.49%**, `read_full_fields` **6.71%**, `handle_softirqs` **3.95%**, and Snapshot decoding **2.89%**; unresolved leaf symbols **5.51%**. Observed chains include `main → poll_all → Bot::poll`, then either `BehaviorState::decide → RawIterRange::fold_impl`, or `ServerPacket::decode → Snapshot::decode_body → read_full_fields`.

`Bot::poll` is about **98% inclusive** throughout; that includes behavior and decoding work, not just ENet polling. `BehaviorState::decide` grows **9.73% → 16.41% → 22.75% inclusive** over the three aligned windows. ENet service stays roughly **46–52% inclusive**. Generator-side queue drops and this workload mix keep generator scheduling/backlog plausible, but do not establish actual per-bot input cadence.

The predefined logging-symbol group accounts for **0.89%** of game workload samples, and the measurement/serialization group **0.07%**. This lowers the priority of an obvious logging CPU hotspot in this run; optimized/inlined work and unresolved symbols prevent treating those groups as complete accounting.

Updated interpretation: serialization/replication remains material before and around onset; ACK-associated reliable-queue processing becomes the clearest late CPU amplifier. Generator polling/behavior remains a competing contribution. Reliable retry feedback, causal receive gaps, packet bursts, queue residence time, and offered input cadence remain unmeasured. No tuning or fix was attempted.

## Recording quality and perturbation limits

Each PID used software **`cpu-clock`, 99 Hz, `--call-graph dwarf,8192`, CLOCK_MONOTONIC**, inherited threads, 256 mmap pages, and no build-id cache updates. Both frozen executables had `.symtab` and `.eh_frame`, but no `.debug_info`; symbol names and unwind stacks were available without rebuilding. DWARF mode captures a bounded user stack for later unwinding. [Upstream perf recording documentation](https://github.com/torvalds/linux/blob/master/tools/perf/Documentation/perf-record.txt).

The bot wrapper stopped itself before exec; the recorder attached to that same PID and acknowledged event enablement before the wrapper continued into the frozen executable. The game recorder was ready before the bot launch. First retained CPU samples were 0.903 s before bot exec on game and 0.452 s after exec on bots; absence of an earlier bot CPU sample is not an attachment delay. Sampling records running CPU, not idle wall time.

| Recording evidence | Game | Generator |
| --- | ---: | ---: |
| Recorder elapsed, including finalization | 48.220554 s | 43.415632 s |
| `perf.data` bytes | 25534345 | 18767105 |
| Decoded / raw sample records | 2973 / 2973 | 2177 / 2177 |
| Samples inside workload | 2930 | 2177 |
| Measured effective samples / target CPU-second | 98.4437 | 98.2829 |
| Measured effective samples / wall-second | 63.0829 | 50.5224 |
| Reported lost-sample / throttle records | 0 / 0 | 0 / 0 |
| Workload samples with ≥2 frames | 2927 / 2930 | 2175 / 2177 |
| Workload samples reaching application `main` | 2927 / 2930 | 2163 / 2177 |
| Workload samples with named leaf | 2671 / 2930 | 2057 / 2177 |
| Workload samples containing any unknown frame | 634 / 2930 | 932 / 2177 |
| Median workload stack depth | 4 | 7 |

Effective CPU-time rates divide samples within first/last process-stat anchors by the corresponding `/proc/PID/stat` CPU delta (100 ticks/s), not by nominal 99 Hz. Game samples belong to the main thread except one exporter-thread sample; all generator samples belong to its main thread. There were no decoder warnings. Raw record sample counts equal decoded counts, with no `LOST`, `LOST_SAMPLES`, `THROTTLE`, or `UNTHROTTLE` records; this is reported loss accounting, not proof against every possible sampling bias.

The supervisor stops at **58 s**, with a remote systemd **59 s** runtime guard and **1 s** stop timeout. `--max-size=60M` and a 60 MiB polling guard leave headroom under a **64 MiB RLIMIT_FSIZE**. Neither duration nor file cap was reached. The game recorder ended by orderly controller stop; the bot recorder ended when its target exited. Perf returned `-2` after SIGINT/finalization on game; its complete sample stream decoded successfully. Some header-only summary fields were unavailable, so counts/times come from actual records and clock anchors, not those empty header fields.

Recorder CPU: game **0.297126 s / 0.616%** of one CPU over its recording window; bots **0.285661 s / 0.658%**. Supervisor CPU: **0.342331 s / 0.710%**, **0.275033 s / 0.633%**. Host/socket collectors: **3.902% game / 4.114% bots**, over their longer full collection windows. Existing Tick observer timing averaged **26.303 µs**, maximum **379.446 µs**. These separate resource measurements do not estimate the causal slowdown from interrupts, stack copies, or changed scheduling. No observer-off comparison was run; baseline/profile timing differences cannot be attributed to profiling.

Perf timestamps were translated with each host's recorded monotonic/UTC anchors. Offset spread during recording was **22.920 µs game / 99.640 µs bots**. Post-run chrony checks reported both clocks synchronized, normal leap status, offsets below 0.1 ms, and root dispersions about 2.0/1.7 ms. Cross-host ordering is appropriate at the one-second onset resolution; no packet-level ordering precision is claimed.

## Frozen inputs and controller

Game SHA-256: `f2bf76c6fa3c28b7fb9b5d52f216061e9c3239999d67bf8a42acadf44dada3a2`.
Bot SHA-256: `8af491831304e1ab913089e3b8f1750ea701e4ccd8993d834bcc30ecfa3e8bdf`.
Native config SHA-256: `bac0bf8947937a334b4fd9e814e1e3a4e15b9753fd3f1c02e185285d26f0d68c`.

The existing game `b1266c1` and bot `642c147` artifacts were hash-checked before and after. The newer bot ramp recorder was **not used**. Settings stayed Strategy 200, 30 Hz input and server Tick, seed 30, 100 ms stagger, difficulty 1.0, default Class rotation, native config/AoI/bandwidth settings from the baseline. Server entropy is not fixed by the bot seed.

Controller invocation was `python3 scripts/load_campaign/udp_profile.py run`. It preserves the baseline argv with only the output namespace changed to `udp-profile-20261021`. Ramp cap **180 s**, post-ramp cap **120 s**, overall swarm service bound **305 s**, join-failure checks every 0.5 s, two-poll collapse gate below 65% of a peak ≥100, stale game observation/log-size guards, and a **420 s** service-restoration timer were active. No packet tracing, buffer changes, qdisc/firewall changes, kernel upgrade/reboot, or Rust build occurred.

Owned implementation: [controller](../../../../../scripts/load_campaign/udp_profile.py), [bounded recorder](../../../../../scripts/load_campaign/udp_profile_record.py), [package provisioning](../../../../../scripts/load_campaign/udp_profile_tools.py), and [offline analysis](../../../../../scripts/load_campaign/udp_profile_analysis.py). The once-only launch marker and remote namespace remain consumed; do not clear them to rerun. `preflight` now also checks the successful disposable sampler validation. The old preflight-only controller is preserved privately.

`ramp_input_cadence = null`, `generator_valid = null`: frozen `bots.ndjson` is empty and no `phase.json` exists. A CPU profile cannot repair that missing offered-load evidence. No new validated capacity is claimed.

## Minimal tool provisioning and remaining installation

Both hosts were checked for idle apt/dpkg ownership and inactive update jobs. A matching-tools simulation proposed five new packages and recommended a separate `linux-perf`; the standalone perf simulation required only **three** new packages. The actual install pinned exactly these versions with `--no-install-recommends --no-upgrade`, a zero lock wait, and `NEEDRESTART_MODE=l`:

- `linux-perf` **7.0.0-38.38**, arm64.
- `libdebuginfod-common` **0.194-4**.
- `libdebuginfod1t64` **0.194-4**, arm64.

**All three remain installed on both hosts.** Before/after dpkg inventories show no existing package version changes or removals. No apt refresh, broad upgrade, extra matching-tools package, bpftrace, or gdb was installed. Package provenance records retain Ubuntu repository metadata, .deb SHA-256 values, simulation output and installation logs. `linux-perf` .deb SHA-256 is `fba7f99201b9949028aa6d78480f58258092962801192be8e99fca970e515a4c`; `/usr/bin/perf` on both hosts hashes to `a8840d2f9c0cf9c28e424aea0af2117c599e88b81b87d99175caa6db8916e9bb` and reports **perf version 7.0.14**, with libdw DWARF unwind support.

Kernel remains **7.0.0-30-generic**; `perf_event_paranoid` remains **4**. Recorders used existing root privileges. Debuginfod lookup was disabled for recording/decoding (`DEBUGINFOD_URLS=`); no source/debug downloads were required.

A disposable C busy process, compiled with omitted frame pointers and unwind tables but no debug info, validated the same 99 Hz / 8192-byte DWARF mode for three seconds: **279/279** known-chain samples on game and **239/239** on bots. An initial game-host validation stopped early because the harness expected `ack\n` but perf returned `ack\n\0`; the gate was corrected and revalidated. This was a controller protocol bug, not kernel denial, and neither disposable check was a game capacity experiment. All validation evidence and failed-attempt history remain preserved.

## Preservation, verified cleanup, and evidence

Fresh pre-run measurement files were copied after stopping the service and SHA-256 verified before restart; the copy was independently checked again after cleanup. The historical 2.7 GiB backup and baseline archives were retained. The original executables/config/drop-in were copied under the new namespace without replacing their originals. Game output redirection was the only temporary service override.

Independent final verification at **12:09:02.469775 UTC** found: ordinary game service active, **zero players**, original unit/config restored, no runtime profile override; both hosts free of swarm, perf, busy validation process, collectors, packet tracers, compiler and package jobs; all temporary profile/swarm/collector/restoration units inactive. Native qdisc/filter/firewall state and closed historical campaign state matched preflight. Both maintenance timers remain active/enabled, update services inactive. Bounded kernel journals had no entries.

Raw evidence is private under `deployment/hetzner/results/udp-profile-20261021/`, with remote originals under `/home/deploy/omega-results/udp-profile-20261021/`. Tool-validation evidence uses the separate remote `udp-profile-tools-20261021` namespace. Both workload bundles and both tool-validation bundles were SHA-256 checked against remote copies before local acceptance. **No remote evidence was deleted.** Raw addresses, process mappings, raw stack addresses and connection details remain in ignored results.

| Evidence | SHA-256 |
| --- | --- |
| `game.tar.gz` | `f85d6fdd61d2e1b79b55dcfea52ea4fa1ee2957a19746359bf4f22ebc4f3104e` |
| `bots.tar.gz` | `bacb200b5702642451c94eaecac6737355aae429fb49aa9a0ce2357ffdce3d2b` |
| `udp_profile.executed.py` | `f74db229a07fdbbafce8ba807d6a60911ec8ea9116c975467c69538f7bc0ddfc` |
| `udp_profile_record.executed.py` | `78653702b58e000bf508a21a01a16cce7557b15b8799024572a5427083ab8906` |
| `manifest.json` | `1764dcfb482d5f8d3909024c7676156f39b74d6caf5fba01aa39e95cfdc4122c` |
| `cleanup.json` | `c996b41f5fb21fe11b8a0bd7c5e1d3ddd5dc79a3ddac6df7ab60774a8332b9d6` |
| `preserved-measurement-sha256.txt` | `270db5616c803183c36476a57a724536f2a118cb3d077d35acc0b84fa0e67b5b` |
| `game tools-evidence.tar.gz` | `1872bbfaf9703cba31fd119c330eb78c82bb6fc6978761e7779a190cb68b68fe` |
| `game/perf.data` | `718ec449a8e635be1b68e2e6212f4aa4d1df41e1b6223e069035ea64a2a6220c` |
| `bots tools-evidence.tar.gz` | `054c48692ade04ec96ae669b31a4e985004c14c8e7105513872b8f1df7559156` |
| `bots/perf.data` | `744270b3f536f45e7cc23dc15937226bfca926c9727acecc4b617391cb7a9f6b` |

No commits, branch changes, Rust edits, baseline harness/report edits, parent-ledger edits, new agents, or additional workload runs were made. Python compilation, analysis assertions, evidence hash checks, cleanup assertions and public-output redaction checks completed. The next diagnostic or implementation decision belongs to the parent.

## Historical read-only preflight — preserved original report

The following records the earlier attempt, before provisioning. Its statements about missing tools and unimplemented execution were true at that time and are superseded by the completed experiment above.

# Strategy 200 CPU profile — prerequisite blocked, 2026-10-21

**No experiment launched.** The read-only preflight for [issue #38](https://github.com/Operatorr/godot-networking-poc/issues/38) found no installed CPU sampler on either isolated CAX11 host. This takes the explicitly authorized “return actionable blocker without wasting an experiment” path. There is no new capacity result or evidence discriminating the ranked hypotheses. The baseline result remains unchanged.

## Blocker and concrete next step

On both hosts, `perf version` returned `bash: line 1: perf: command not found`. Neither PATH nor the usual `/usr/lib/linux-tools/*/perf`, `/usr/lib/linux-tools-*/perf`, and `/opt/*/bin/perf` locations supplied perf. No `bpftrace`, `gdb`, `eu-stack`, or `sysprof-cli` was found. `/usr/bin/strace` exists, but syscall tracing does not provide sampled CPU symbols/call stacks; tracing every network syscall risks changing the read scheduling under investigation. It was not attached.

Both hosts run kernel `7.0.0-30-generic`. Read-only package metadata lists an uninstalled matching `linux-tools-7.0.0-30-generic` candidate **7.0.0-30.30** and an uninstalled `linux-perf` candidate **7.0.0-38.38**. The parent can provision a compatible perf executable on both hosts, then validate software `cpu-clock` recording and unwinding on a short disposable process before dispatching the one workload experiment. No package installation, apt refresh, or kernel setting change was performed here. `perf_event_paranoid=4` on both hosts means the eventual sampler needs appropriate privilege; passwordless sudo and a root capability bounding set including `CAP_PERFMON` were observed, but actual `perf_event_open` access was **not tested**.

The frozen executables both contain `.symtab`, `.eh_frame`, and `.eh_frame_hdr`; no `.debug_info` section was observed. These are promising prerequisites for symbol names and DWARF unwind information, not proof that complete stacks will unwind. No rebuild is necessary merely to inspect these existing symbols. Validate stack coverage before selecting FP versus bounded DWARF stack sampling.

The still-pending experiment remains Strategy 200, 30 Hz input/Tick, seed 30, 100 ms stagger, difficulty 1; ramp cap 180 s and post-ramp cap 120 s. Proposed recording remains 99 Hz software CPU-clock on each target PID, at most 60 s and 64 MiB per host, with explicit stop/size guards and accounting for sample loss and profiler resource use. Those are **planned limits, not measurements**.

## Read-only preflight outcome

Completed at **2026-10-21T11:56:32.226398+00:00**. All non-profiler gates passed:

- Exact game SHA-256 `f2bf76c6fa3c28b7fb9b5d52f216061e9c3239999d67bf8a42acadf44dada3a2`; exact bot SHA-256 `8af491831304e1ab913089e3b8f1750ea701e4ccd8993d834bcc30ecfa3e8bdf`. Both existing remote artifacts were inspected; no working-tree binary was used.
- One ordinary game server, PID 559268, active/enabled with zero players and the unchanged native config. No swarm, collector, profiler, compiler, or package job was active. No `omega-udp-*` units were loaded during discovery.
- Available disk: **17,342,197,760 bytes game**, **25,197,932,544 bytes bots** at final preflight. Native fq_codel, empty ingress/egress filters, and no `omega_measure` firewall collector.
- Both update timers active/enabled, update services inactive, next scheduled jobs hours away. No maintenance setting was changed.
- Remote `/home/deploy/omega-results/udp-profile-20261021` does not exist. No launch marker was reserved. The planned experiment remains unconsumed.

The previous game archive and final bot archive were SHA-256 checked remotely and against their existing local copies:

```text
game.tar.gz       e318b27876da5f60ad623162ba046e93c54c2a1f8d932f51aebe5a56d454c838
bots-final.tar.gz 43af964645432973d162bdc2aab4b82364ee8285b877469e34504f45dd99e42d
```

The historical 2.7 GiB idle measurement backup remains in the baseline namespace. Its checksum-manifest hash still matches the baseline report (`f4439b76cf37faf957e1f9574a5654df36490ad9d850fd7686e1b4fcd6375a15`); the full 2.7 GiB data was not rehashed or recopied. The fresh current measurement directory was about 2.5 MB during inspection and continues to belong to the unchanged running service. Because there was no restart/truncation or mutation, no new preservation copy was needed. No prior namespace, bundle, or closed campaign state was modified or removed.

## Evidence, nulls and handoff

[Compact sanitized preflight output](profile-preflight-summary.json) records the gate results. Private evidence lives under `deployment/hetzner/results/udp-profile-20261021/`: discovery/readiness files, preservation proofs, and `preflight-20261021T115614867733Z/` with individual command results and `summary.json`. Connection addresses and raw host/process/firewall output remain there.

The owned [udp_profile.py](../../../../../scripts/load_campaign/udp_profile.py) implements only the read-only readiness gate adapted from the baseline workflow. Invoke `python3 scripts/load_campaign/udp_profile.py preflight`; its intentional exit status is **2**, with `experiment_started=false` and `execution_implemented=false`. The bounded recording/launch path must be completed after the profiler prerequisite is resolved; this script must not be mistaken for an executed profiler controller.

New profile coverage, loss, perturbation/overhead, top symbols/call stacks before/after onset, receive-gap distribution, actual ramp input cadence and generator validity are all **null**, not zero. No CPU samples or new socket/Tick experiment evidence were collected. The prediction remains untested: a bounded profile spanning onset should distinguish dominant transport, simulation/replication, logging, and generator work; it cannot by itself establish reliable-retry feedback or causal receive gaps.

Cleanup: no restoration was required because every remote action was read-only. The ordinary game service remained running with zero players; network and maintenance settings were left intact. No swarm, collector, tracer, or profiler was started or left behind. No rerun, subagent, Rust change/build, baseline-controller/report edit, ledger edit, or commit occurred.
