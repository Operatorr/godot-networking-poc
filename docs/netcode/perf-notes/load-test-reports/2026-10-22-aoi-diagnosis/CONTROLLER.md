# Matched AoI diagnostic controller adaptation

Namespace: `aoi150-20261022`. Candidate: `4c33a3e0bdccad352f82bbe00cdabf8e907a84d8`.

The new controller derives from reviewed `udp_send150.py`; historical scripts remain untouched. Both game and bots build from the exact committed candidate in new remote checkouts. Both hosts produced identical game and bot hashes. Prebuild inventory recorded original binaries, evidence archives, service, config, maintenance and network state before changes.

The original send150 config is checked byte-for-byte against `0abd2a9041dc33023ff924cae334ce25683838a0c0726cfd8fcb5a0000332370`. Existing workload, native bot buffers, wire collector, strict assertions and capacity gates are retained. `OMEGA_AOI_AUDIT=1` is required; exact audit header validation precedes bots. Audit rows have the candidate's 2-million-row guard and controller measurement evidence is limited to 1 GiB. Existing capture, workload and automatic restoration bounds remain.

The once-only local namespace reservation prevents another launch. Restoration removes the owned override, restores the original executable and measurement destination, and verifies audit environment removal. A separate read-only audit checks original artifacts and archive hashes after cleanup.

Before launch, 21 tests passed across `test_aoi150`, `test_aoi150_correlation`, `test_udp_cleanup`, and `test_atomic_publish`. These exercise config identity, runtime/header prerequisites, publication and cleanup flow, and missing/ambiguous/false/true anomaly attribution with f32 distance. Test/source hashes and complete build/environment journals are retained in the ignored build evidence archive.

The server audit scores authoritative emission separately from delivered bot evidence. Standalone strict AoI remains failure/unknown if same-Snapshot observer position is omitted. All retained legacy anomalies require a unique observer/Tick/server_ms match and exact Tick UTC membership. Cumulative emitted baseline/delta counts are reconciled by Tick and final totals; missing evidence cannot pass. No capacity advance is authorized by this observation.
