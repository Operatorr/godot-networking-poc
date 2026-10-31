# Appendices A–D (shared by drafts A, C1 and C2)

> Outside every draft's word budget. Each draft links here. Sections are labelled by the draft
> section that uses them: "A §3" is Article A section 3; C1 and C2 sections are named in brackets.

---

## Appendix A. Formula sheet

Units: B = byte, b = bit, kB = 1000 B, Mbit = 10⁶ bits. All rates decimal unless marked KiB.
Source: [`replication-math.md` §11](../research/replication-math.md), verified against
`rusty_enet` 0.4.0 and RFCs 768, 791, 8200, 9000.

```
Per-datagram overhead
  H_d (IPv4, ENet unreliable, no reliable/ack/checksum) = 20 + 8 + 2 + 8 = 38 B
  H_d (IPv6, with sent_time)                           = 40 + 8 + 4 + 8 = 60 B
  (+2 B ENet header when a reliable command shares the datagram; +8 B per piggy-backed ACK)

Payload limit
  Max ENet payload inside IPv6 minimum MTU             = 1280 − 60 = 1220 B   → use L = 1200 B
  ENet fragmentation threshold (default MTU 1392)      = 1392 − 4 − 24 = 1364 B

Quantization
  bits(range, step) = ceil( log2( range/step + 1 ) )

Snapshot size and rate
  r  = floor( (L − H_s) · 8 / b_e )          records per datagram
  d  = ceil( k / r )                          datagrams per Snapshot
  D  = f · ( ceil(k · b_e / 8) + d · (H_s + H_d) )     downstream per client
  U  = f_in · (I + H_d)                       upstream per client
  E  = N · D                                  server egress

Growth
  k_naive = N − 1                    → E = Θ(N²)
  k_AoI   = min(N − 1, ρπR², k_max)  → E = Θ(N · k)

Delta
  b_delta = p · b_changed + (1 − p) · b_unchanged      savings = 1 − b_delta / b_full

CPU per Tick
  C_tick ≈ C_sim + N · C_aoi + N · k · c_rec + N · d · c_send      budget = 1000 / f_tick ms

Transfer
  1 Gbit/s sustained = 125 MB/s × 2,592,000 s ≈ 324 TB per 30-day month
  B_month = r_out × CCU × 86,400 × calendar_days      (sum 12 calendar months for a year;
                                                     apply allowance rounding per month)
```

**Omega's measured constants (A §5, C2 "wire format").** H_s = 16 B delta / 12 B Baseline;
b_e = 49 b moving player, 54 b projectile, 53 b monster; I = 22 B; f = f_in = 30 Hz; L = 1200 B;
AoI enter 1000 u / exit 1100 u; Arena 2000 × 2000 u.

**Omega cost model (fitted at N = 50, default bots, pre-fix build; extrapolated).**

```
R(N) ≈ 1.3 KB/s + 0.42·(N−1)·157 + 0.42·N·1.7·209 + 30·N    [B/s per recipient, downstream payload]
     ≈ 1.3 KB/s + ~245 B/s · N
Snapshot reaches the 1200 B budget at  N ≈ (1200 − 16) / ((0.42·157 + 0.42·1.7·209) / 30) ≈ 165
Wire ≈ payload × 1.16 downstream
```

**Derived checks used in the drafts.** All reproduced with a throwaway script implementing the
formulas above.

| Id | Calculation | Result |
|---|---|---|
| D1 | 1,080 players / 36 cores; × 128 Hz; / 30 Hz | 30 players/core; 3,840 player-Ticks per core-second; 128 players/core at 30 Hz |
| BF4 | 4 Instances × 64 × 30 Hz vs 1 × 64 × 60 Hz | 7,680 vs 3,840 player-Ticks per box-second |
| D7 | 20 × 19; 1,500 × 1,499 | 380; 2,248,500 |
| D9 | 36,704.20 / 21,866.95; 3,670,419.81 / 1,093,347.36 | × 1.68 per player; × 3.36 total |
| D10 | 26,000 × 1.16 vs 36,704 | 30,160 B/s model vs measured; measured +22% |
| D11 | 100 × 30 / 0.397 | ~7,560 player-Ticks per core-second (naive) |
| D12 | 3,670,419.81 × 86,400 × 30; × 365 | 9,513,728,147,520 B; 115,750,359,128,160 B |
| Rust | 105 KB/s / 6% / 122 players | ~1.75 MB/s total; ~14.3 kB/s per player |

---

## Appendix B. Full bit layouts

Source of truth: `rust/protocol/src/{lib,types,bits,quant,client,snapshot,server}.rs`. Layouts
verified at commit `62fbfc3`; the correctness fixes changed no layout. Bit fields are LSB-first;
any byte-sized write pads the partial byte first.

### B.1 Framing and channels

```
ENet datagram (one per peer per flush; ENet coalesces up to 32 commands)
  [IPv4 20 + UDP 8]                                    28 B   (IPv6: 48 B)
  [ENet header: u16 peer_id | flags]                    2 B
    [+ u16 sent_time]                                  +2 B   only if a reliable command is present
  [command]*   4 B command header + per-type fields + payload
               SEND_UNRELIABLE 8 B · SEND_RELIABLE 6 B · ACKNOWLEDGE 8 B · SEND_FRAGMENT 24 B

Game packet inside a command:  [u8 type][payload]   (no length field)
  client → server types 1–6, server → client types 64–68 (disjoint)
```

| Ch | ENet mode | Server → client | Client → server |
|---|---|---|---|
| 0 | unreliable sequenced | delta Snapshots, ActionConfirm | — |
| 1 | reliable ordered | Baselines, AuthResult, Game events, ServerMetrics | ConnectAuth, BaselineAck, RequestFullState, RespawnRequest, LocalHitReport |
| 2 | unreliable sequenced | — | PlayerInput |

### B.2 `PlayerInput` (type 2, ch2), 22 bytes, byte-aligned

```
byte  0      type = 2                          u8
byte  1      sequence                          u8 (wraps)
bytes 2–3    input_flags                       u16: UP DOWN LEFT RIGHT SHOOT ABILITY SPRINT INTERACT DASH (bits 0–8)
bytes 4–5    aim_angle                         i16, trunc(rad × 100)
bytes 6–9    position x, y                     2 × i16, trunc(u × 10)
bytes 10–13  velocity x, y                     2 × i16, trunc(u/s × 10)
bytes 14–17  cursor x, y                       2 × i16, trunc(u × 10)
bytes 18–19  client_render_tick                u16 (low 16 bits of server Tick)
bytes 20–21  client_rtt_ms                     u16
```

Wire: 28 + 2 + 8 + 22 = 60 B per datagram; 1.8 KB/s at 30 Hz.

### B.3 Snapshot header (type 65), byte-aligned

```
type            u8      = 65
server_tick     u32
server_ms       u32     server monotonic ms (clock-sync heartbeat)
flags           u8      bit0 IS_DELTA, bit1 BASELINE (both set = rejected)
baseline_tick   u32     only when IS_DELTA
entity_count    u16     decoder cap 4096
→ 16 B delta header, 12 B Baseline header; record bitstream follows, final byte zero-padded
```

### B.4 Typed entity id

| Kind (2 b) | Entity | Offset bits | Id range | Total id bits |
|---|---|---:|---|---:|
| 0 | player | 10 | 1–999 (id = offset) | 12 |
| 1 | projectile | 15 | 10000–29999 (offset = id − 10000) | 17 |
| 2 | monster | 14 | 30000–39999 | 16 |
| 3 | world effect | 14 | 40000–49999 (four 2,500-id sub-bands) | 16 |

### B.5 Records

```
Baseline record:  [typed id][anim 3 b][entity_flags 16 b][qx 16 b][qy 16 b]
Delta record:     [typed id][mask 5 b] then, by mask bit:
                    bit0 POSITION  → qx, qy             32 b
                    bit1 ANIMATION → anim                3 b
                    bit2 FLAGS     → entity_flags       16 b
                    bit3 REMOVED   → nothing
                    bit4 FULL      → anim, flags, qx, qy 51 b
                  decode precedence: FULL before REMOVED; mask-0 entities are never encoded
```

| Record shape | Player | Projectile | Monster / world effect |
|---|---:|---:|---:|
| Baseline | 63 | 68 | 67 |
| Delta FULL | 68 | 73 | 72 |
| Delta POSITION | 49 | 54 | 53 |
| Delta POSITION + ANIM | 52 | 57 | 56 |
| Delta POSITION + FLAGS | 65 | 70 | 69 |
| Delta REMOVED | 17 | 22 | 21 |

### B.6 Other per-Tick and broadcast packets

| Packet | Bytes | Recipients | Rate |
|---|---:|---|---|
| ActionConfirm (66, ch0) | 16 | owner | each Tick with input |
| `PROJECTILE_FIRED` (67/12, ch1) | 12 | **all peers** | every shot |
| `DAMAGE` (67/1) | 9 | all peers | per hit |
| `KILL` / `KILL_PVP` | 6 | all peers | per kill |
| `RESPAWN` | 10 | all peers | per respawn |
| `EXP_GAIN` | 8 | all peers | per nearby player per monster kill |
| `PLAYER_INFO` | 11 + name | all peers | join, hydrate, level-up |
| `LEADERBOARD_UPDATE` | 7 + 6 × rows (≤ 67) | all peers | on kill (coalesced per Tick) and every 5 s |
| `PROGRESS` | 13 | owner | XP change |
| `SERVER_METRICS` (68) | 34 | all peers | 1 Hz |
| `BaselineAck` (client) | 5 | server | per Baseline |

### B.7 Delta and Baseline rules, as built after the correctness fixes

- Per-peer cache of the last sent `{position, animation, flags}`. POSITION is set when an axis moved
  by ≥ 0.05 u (half a quantization step); ANIMATION / FLAGS on any change; FULL for entities new to
  the peer.
- Baseline every 100 Ticks on ch1 reliable; the client ACKs; dependent ch0 deltas wait for the exact
  pending Baseline ACK. Old ch0 deltas can't recreate entities after a newer Baseline.
- Budget: the encoded delta (header, rounding and pinned REMOVED records included) stays under
  1,200 B; oversized pinned sets go out as a reliable Baseline.
- AoI 1000 enter / 1100 exit (strict `>`), spatial grid cell 275 u; priority = importance (player 10,
  projectile 8, monster / world effect 4) + Ticks since sent − LOD penalty (0 / 4 / 8 at ≤ 400 /
  ≤ 1000 / beyond) + change bonus. Greedy admission.

---

## Appendix C. How to reproduce

**Local, single machine** (no campaign tooling, no remote hosts):

```bash
# build
./scripts/build_server.sh
cd rust && cargo build --release -p omega-load-test && cd ..

# terminal 1: server under test (dev mode, unsigned tickets)
./scripts/run_server.sh --mode arena --port 8081      # or: omega-server --config <cfg> --allow-unsigned-tickets

# terminal 2: bot swarm
./scripts/run_load_test.sh --scenario baseline                         # 50 bots, 120 s
./scripts/run_load_test.sh --bots 100 --duration 300 --behavior strategy --input-hz 30 --stagger 100 --seed 30 --difficulty 1   # campaign settings
```

Scenarios and flags (`--behavior`, `--difficulty`, `--seed`, `--bandwidth-budget`, `--rate-budget`,
`--assertions`, `--aoi-exit-radius`) are documented in
[`rust/load_test/README.md`](../../rust/load_test/README.md). `stress` (200 bots) needs a config
with `max_players >= 200`.

**The remote CAX11 campaign** used `scripts/load_campaign/` (`one_pass.py init | preflight |
resolve-preflight | all`, plus the compact `article-points-v1` collector). It needs two provisioned
hosts and the private configuration recorded in each report. Build identities, configs, gates and
exact windows are in the reports:

- Original build: [`2026-10-14-one-pass/`](../netcode/perf-notes/load-test-reports/2026-10-14-one-pass/README.md)
- Diagnosis: [`2026-10-21-udp-diagnosis/CONCLUSION.md`](../netcode/perf-notes/load-test-reports/2026-10-21-udp-diagnosis/CONCLUSION.md)
- Fixed build: [archived campaign at `fcf4f62`](https://github.com/Operatorr/godot-networking-poc/tree/fcf4f62c3d625a24caf8c462e186c8887fa98ce9/docs/netcode/perf-notes/load-test-reports/2026-10-22-clean-runs)
  (game SHA-256 `de92e120bb863948fc4c55fe525d200ac6ebc0d0d214d453ed3efeab159208db`,
  config SHA-256 `0abd2a9041dc33023ff924cae334ce25683838a0c0726cfd8fcb5a0000332370`)

> [AUTHOR] Any new remote experiment needs its own separately reviewed bounded plan; the article
> map authorizes none. The reproduce appendix should say "here is how we did it", not invite
> readers to run our hosts.

---

## Appendix D. Sources, grouped by section

Tags: [P] primary, read directly · [S] first-party statement read through the press or a mirror ·
[U] unverified · [O] observed third-party data · [D] our arithmetic.

### Our own evidence (A §0, §6–§8; C2)

- [Original CAX11 checkpoint and hypotheses](../netcode/perf-notes/load-test-reports/2026-10-14-one-pass/CAX11-CONCLUSION.md),
  [Strategy extension](../netcode/perf-notes/load-test-reports/2026-10-14-one-pass/STRATEGY-EXTENSION.md),
  [one-pass README](../netcode/perf-notes/load-test-reports/2026-10-14-one-pass/README.md),
  [CPU report](../netcode/perf-notes/load-test-reports/2026-10-14-one-pass/CPU.md)
- [Fixes and open checks (round 1)](../netcode/perf-notes/load-test-reports/2026-10-14-single-run/fixes-and-open-checks.md)
- [UDP diagnosis conclusion](../netcode/perf-notes/load-test-reports/2026-10-21-udp-diagnosis/CONCLUSION.md)
- [Correctness fixes extracted to master](../netcode/perf-notes/issue39-correctness-fixes.md), [PR #44](https://github.com/Operatorr/godot-networking-poc/pull/44)
- [Final assessment (archived)](https://github.com/Operatorr/godot-networking-poc/blob/fcf4f62c3d625a24caf8c462e186c8887fa98ce9/docs/netcode/perf-notes/load-test-reports/2026-10-22-clean-runs/FINAL-ASSESSMENT.md),
  [clean Strategy 150](https://github.com/Operatorr/godot-networking-poc/blob/fcf4f62c3d625a24caf8c462e186c8887fa98ce9/docs/netcode/perf-notes/load-test-reports/2026-10-22-clean-runs/clean-strategy150-r2-20261022.md)
- [Accepted bounded results audit](https://github.com/Operatorr/godot-networking-poc/issues/31#issuecomment-6382173465) (author-accepted 2026-10-25)
- [Idle150 delivery follow-up](https://github.com/Operatorr/godot-networking-poc/issues/45), [Strategy overload follow-up](https://github.com/Operatorr/godot-networking-poc/issues/46), [Stage 4 deferred evidence](https://github.com/Operatorr/godot-networking-poc/issues/47)
- Code: `rust/protocol`, `rust/server`, `rust/load_test`; [wire-format research](../research/omega-wire-format-and-cost.md)

### Industry case studies (A §2; C1 "the ceiling")

Full table and every link: [`realtime-player-caps.md`](../research/realtime-player-caps.md).

- **id Software** [P]: Quake III `q_shared.h`, `sv_init.c`, `cl_main.c`, `net_chan.c` (GPL source, pinned commit)
- **Valve** [P]: Source SDK 2013 `shareddefs.h` L245–257; Source Multiplayer Networking (Valve Developer Wiki); GameNetworkingSockets `steamnetworkingsockets_internal.h`
- **Riot** [P]: Randall, *VALORANT's 128-Tick Servers* (2020); deWet & Straily, *Peeking into VALORANT's Netcode* (2020)
- **Epic** [P]: Replication Graph docs; Fortnite State of Development v5 (2018)
- **Respawn / EA** [P]: *Servers & Netcode Developer Deep Dive* (2021)
- **Activision** [S]: Charlie INTEL (150), TechRadar and VGC (100)
- **CIG** [S/P]: Letter from the Chairman; Server Meshing Test E AAR; Alpha 4.0 EPTU notes
- **Zipper / Sony** [P]: *Five Things You Didn't Know About MAG* (PlayStation Blog, 2011)
- **SOE / Daybreak** [P/P*]: Guinness (1,158); Wrel continent-cap post (mirror)

### Battlefield and Rust (A §2–§3; C1)

Full note: [`fps-caps-battlefield-rust.md`](https://github.com/Operatorr/godot-networking-poc/blob/research/fps-caps-battlefield-rust/docs/research/fps-caps-battlefield-rust.md) (research branch).

- **DICE / EA** [P]: BF4 High Tickrate BETA PDF (Sirland, 2015); Battlelog *Addressing "Netcode" in BF4* and *High Frequency Bubble* (2014); BF2042 Update 4.1 notes; BF2042 Core Feedback: Maps; BF6 Open Beta Debrief; Sirland on X (BF V, BF6, REDSEC). [S]: Söderlund via GameRevolution / TheSixthAxis (2011); Bach via GameWatcher; Insider Gaming (REDSEC); PC Gamer via inkl (BF6 64)
- **Facepunch** [P]: Friday Devblog 16; Devblogs 42, 58, 171; The Performance Update; Maintenance; Shipshape; Spring Clean; Crafting Update; Bags to Riches; commits 549058, 579925, 586937, 587940, 715823. [S]: decompiled convars (RustChangelog), CustomNetworkRange plugin docs. [O]: Rustalyzer, 2026-10-15

### Replication math (A §3; C1 "the math"; C2 recap)

Full derivations: [`replication-math.md`](../research/replication-math.md).

- RFC 768 (UDP), RFC 791 (IPv4), RFC 894 (Ethernet), RFC 8200 (IPv6), RFC 9000 §14 (QUIC datagram size)
- ENet `protocol.h` / `enet.h` (lsalzman/enet); `rusty_enet` 0.4.0 crate source
- Fiedler, Gaffer On Games: *Snapshot Compression*, *Snapshot Interpolation*, *State Synchronization*, *Deterministic Lockstep*, *Serialization Strategies*, *Packet Fragmentation and Reassembly*
- Frohnmayer & Gift, *The TRIBES Engine Networking Model*
- Quake III `qcommon.h`, `msg.c`, `net_chan.c`

### Tab-target MMOs (A §4; C1 "MMOs")

Full note: [`mmo-scaling-tab-target.md`](../research/mmo-scaling-tab-target.md).

- **Blizzard** [P]: *Engineer's Workshop: Recreating the Ahn'Qiraj War Effort* (2020); Celestalon on 400 ms batching (2014); Kaivax, *Spell Batching in Classic* (2019); Birmingham layering AMA relay (2019); patch 3.2.0 notes
- **CCP** [P]: Masterplan, *Drakes of Destiny* 1–2 (2010); Veritas, *Introducing Time Dilation* (2011) and follow-up (2012); Dolan, *B-R5RB* (2014); FWST-8 and M2-XFE posts
- **ArenaNet** [P]: Loew, *World vs. World: The End of Culling* (2013)
- **Sandbox Interactive** [P, via search index]: *How Albion Online Tackles ZvZ Performance*; Korn, *Cluster Queue* (2021)
- **Academic**: Claypool & Claypool, *Latency and Player Actions in Online Games*, CACM 49(11), 2006; Molnár & Szabó, *On the scaling characteristics of MMORPG traffic*, Híradástechnika 2008

## Recovered June evidence (2026-10-31)

The [complete historical inventory and reconciliation](../netcode/perf-notes/load-test-reports/2026-06-recovered/SUMMARY.md) contains all nineteen reports' requested/connected populations, duration, endpoint category, last rolling Tick statistics, bandwidth, RTT, loss and original gate outcomes. Its [SHA256 inventory](../netcode/perf-notes/load-test-reports/2026-06-recovered/inventory.json) also identifies the historical Markdown/HTML interpretation from `feature/performance-minmaxxing`. Original bytes stay in the ignored `raw/` directory beside the summary.

Both previously pasted summaries match recovered files. A and C2 now cite recovered evidence for the 32.9 Hz estimator example and retain the 99-connected-of-200-requested stress attempt as historical context only. Fourteen reports target loopback; five target the remote host, which the author identifies as DigitalOcean Singapore with this computer generating the load. Missing build/config pins, generator utilization and full-window server counters prevent controlled performance or economics comparisons. Existing `[MEASURE]` slots remain unfilled.
