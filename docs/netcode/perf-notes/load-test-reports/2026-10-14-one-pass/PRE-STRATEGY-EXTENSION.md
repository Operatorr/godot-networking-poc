# Ladder status before the Strategy overload continuation

Recorded before any 200/250/500/750/999 Strategy continuation run. This is the completed lower ladder; it is not evidence for untested higher populations.

| Workload | Completed results |
| --- | --- |
| Movement | Passed 50, 100, 150 |
| Combat | Passed 50, 100; 150 failed offered-load validation |
| Clustered | Passed 50; 75 and 100 had kernel UDP errors |
| Strategy | Passed 50, 100; 150 failed offered-load validation |

Only Strategy was scheduled above 150. None of 200, 250, 500, 750 or 999 had run at this checkpoint. Invalid offered load does not establish a server capacity ceiling.

Additional completed boundary observations: Combat 125 had valid 30 Hz offered load but game-host UDP buffer errors. Strategy 125 had approximately 30 Hz self-reported generation, but some wire input rates fell below the per-peer 29.7 Hz gate and game-host UDP buffer errors occurred. Idle 100/150 passed. Native pre-impairment combat 100 passed; the already-started delay25 observation is finishing before handing the hosts over to Strategy.

The corrected Strategy 100 and movement 150 runs have explicit replacement identities. The earlier truncated Strategy 100 capture and interrupted movement 150 attempt remain preserved. [Original state at this checkpoint](pre-strategy-extension-state.json), [100-player checkpoint](checkpoint-100.json) and [CPU evidence](CPU.md) record source measurements and limitations.

## Operator amendment

The operator explicitly requests continuation at **Strategy 200, 250, 500, 750 and 999**, despite lower-rung offered-load failures, to observe further limits. Each new run is assigned to a separate subagent. Runs are sequential because the same isolated game/bot pair is shared. One subagent reports its completed observation or failed attempt to the parent; the parent records it before dispatching the next rung.

These observations extend overload characterization. The earlier first-failure boundaries and highest-stable populations are preserved. Requested player counts are never substituted for actual maintained population or 30 Hz input load. A higher-rung failure is retained and does not automatically cancel the other explicitly requested rungs; an unusable collector or inaccessible host must be repaired before another run can start. No passing cell is repeated.

Each rung keeps the pinned game/bot binaries, native network, original settings, 100 ms join stagger, 60-second global warmup and 300-second measurement where ramp completes. Compact collection retains CPU timelines/peaks, per-bot cadence, actual population, Tick statistics, traffic, UDP/application errors, backlog/delivery points and bounded diagnostics. Failure during ramp remains an unscored attempt; it is not relabelled as a five-minute observation.

The ongoing network/transfer coordinator is suspended for this priority change. Its existing evidence is retained; broader matrix coverage and tracker resolution remain pending. The parent owns dispatch and writes a durable extension ledger so progress does not depend on conversation context.
