# Rust stack — implementation notes for the port

**Scope:** the concrete library APIs the port builds on, per migration-spec decisions
[D2, D5–D8](../migration-spec.md). Researched 2026-06-11 against docs.rs, the godot-rust book,
Godot class docs, and the actual published crate sources (rusty_enet 0.4.0 tarball,
Godot `modules/enet` source).

Sections: [rusty_enet](#1--rusty_enet-040-server-transport) ·
[godot crate / gdext](#2--godot-crate-05x-gdext--client-extension) ·
[Godot ENetConnection](#3--godot-46-enetconnection-gdscript-client-transport) ·
[Auth / HTTP / observability crates](#4--supporting-crates-ed25519-http-tracing-metrics) ·
[Wire-compat risks](#wire-compat-risks) · [Crate pins](#recommended-crate-pins) ·
[Workspace layout](#workspace-layout)

---

## 1 — `rusty_enet` 0.4.0 (server transport)

ENet **1.3.18** (upstream commit `2662c0d`) transpiled to Rust and made socket-agnostic.
`std::net::UdpSocket` works out of the box. The entire API is wrapped in safe Rust.

> ⚠️ **The GitHub `master` branch has a different (post-0.4) API** — `Host::create(...)`,
> `host.send(peer_id, ...)`, `connect() -> PeerID`. Everything below is the **published 0.4.0**
> API (`Host::new(socket, HostSettings)`, `peer.send(...)`). Read docs.rs/rusty_enet/0.4.0, not
> master. Pin `=0.4.0`.

### Host creation

```rust
use std::net::UdpSocket;
use rusty_enet as enet;

let socket = UdpSocket::bind("0.0.0.0:8081")?;          // Socket::init sets nonblocking(true)
let mut host = enet::Host::new(
    socket,
    enet::HostSettings {
        peer_limit: 1024,        // default: PeerID::MAX
        channel_limit: 3,        // our channel plan (D2); default: 255. Cannot be 0.
        ..Default::default()     // checksum: None, compressor: None  ← MUST stay None (see wire-compat)
    },
)?;
```

`HostSettings` fields (0.4.0 source, `src/host.rs`):

| Field | Type | Default |
|---|---|---|
| `peer_limit` | `usize` | `PeerID::MAX` |
| `channel_limit` | `usize` | 255 (`PROTOCOL_MAXIMUM_CHANNEL_COUNT`) |
| `incoming_bandwidth_limit` / `outgoing_bandwidth_limit` | `Option<u32>` B/s | `None` (Some(0) is an error) |
| `compressor` | `Option<Box<dyn Compressor>>` | `None` |
| `checksum` | `Option<Box<dyn Fn(&[&[u8]]) -> u32>>` | `None` |
| `time` | `Box<dyn Fn() -> Duration>` | `time_since_epoch` |
| `seed` | `Option<u32>` | `None` (random) |

The crate ships `enet::RangeCoder` (ENet's built-in range coder) and `enet::crc32` if compression/
checksum are ever wanted — **both sides must opt in together** (Godot: `compress(COMPRESS_RANGE_CODER)`;
Godot never sets a checksum, see wire-compat).

### Service loop (non-blocking, fits the D8 tick thread)

`service()` takes **no timeout** and never blocks: the bundled `UdpSocket` impl maps `WouldBlock`
to "no packet" (`src/socket.rs`). The tick loop owns all sleeping.

```rust
// 0.4.0 examples/server.rs (verbatim, trimmed):
loop {
    while let Some(event) = host.service().unwrap() {
        match event {
            enet::Event::Connect { peer, .. } => {
                println!("Peer {} connected", peer.id().0);
            }
            enet::Event::Disconnect { peer, .. } => {
                println!("Peer {} disconnected", peer.id().0);
            }
            enet::Event::Receive { peer, channel_id, packet } => {
                // packet.data(): &[u8]
                _ = peer.send(channel_id, &packet);   // echo
            }
        }
    }
    std::thread::sleep(Duration::from_millis(10));
}
```

Signatures (0.4.0):

```rust
pub fn service(&mut self)      -> Result<Option<Event<'_, S>>, S::Error>  // does socket I/O
pub fn check_events(&mut self) -> Option<Event<'_, S>>                    // drains queued events only
pub fn connect(&mut self, address: S::Address, channel_count: usize, data: u32)
    -> Result<&mut Peer<S>, NoAvailablePeers>
pub fn peer_mut(&mut self, peer: PeerID) -> &mut Peer<S>       // panics if invalid; get_peer_mut -> Option
pub fn broadcast(&mut self, channel_id: u8, packet: &Packet)   // all connected peers (ignores AoI — avoid)
pub fn flush(&mut self)                                        // force-send queued packets now
```

`Event<'a, S>` borrows the peer; call `.no_ref()` to get an `EventNoRef` carrying a plain
`PeerID` (a `usize` newtype) you can store across the tick.

**Tick integration (D8).** Drain `service()` until `None` at the top of every 30 Hz tick, send
per-peer snapshots, then sleep the remainder. ENet's retransmit/ack timers are driven by
`service()`/`flush()` — with a single 33 ms service point, acks ride out up to one tick late and
measured RTT inflates by up to ~33 ms. If that matters, sleep in small slices (e.g. 1–5 ms)
calling `service()` each slice, or call `flush()` right after queuing the tick's sends.

### Sending — packet kinds and the Godot flag mapping

Constructors (`src/packet.rs`): `Packet::reliable`, `Packet::unreliable` (**sequenced** — this is
the snapshot/input mode), `Packet::unreliable_unsequenced`, `Packet::always_unreliable`,
`Packet::always_unreliable_unsequenced`. Data: anything `ToRawPacket` (`&[u8]`, `Vec<u8>`,
`Box<[u8]>` — `Vec<u8>` is zero-copy).

Exact flag mapping from 0.4.0 source — this is the wire-level rosetta stone vs Godot:

| `PacketKind` | ENet flags on the wire | Godot `ENetPacketPeer` flags |
|---|---|---|
| `Unreliable { sequenced: true }` (= `Packet::unreliable`) | `0` | `0` (no flags) |
| `Unreliable { sequenced: false }` | `UNSEQUENCED` | `FLAG_UNSEQUENCED` (2) |
| `AlwaysUnreliable { sequenced: true }` | `UNRELIABLE_FRAGMENT` | `FLAG_UNRELIABLE_FRAGMENT` (8) |
| `Reliable` | `RELIABLE` | `FLAG_RELIABLE` (1) |

```rust
// D2 channel plan, server side:
peer.send(0, &enet::Packet::unreliable(snapshot_bytes))?;  // ch0 STATE_UPDATE — unreliable sequenced
peer.send(1, &enet::Packet::reliable(event_bytes))?;       // ch1 GAME_EVENT — reliable ordered
// ch2 PLAYER_INPUT arrives from the client; server replies on 0/1.
```

> ⚠️ `PacketKind::Unreliable` docs: *"packets of this kind will be sent reliably if they are too
> large to fit within the maximum transmission unit (MTU)."* Default MTU is **1392** bytes
> (`HOST_DEFAULT_MTU`, same in Godot — same ENet version). An oversized ch0 snapshot silently
> becomes reliable-fragmented and reintroduces head-of-line blocking. Keep snapshot payloads
> comfortably under ~1300 B (the AoI byte-budget scheduler already exists for this), or use
> `always_unreliable` (loses the whole packet if any fragment drops — acceptable for snapshots).

### Peer management, RTT, timeouts

```rust
pub fn id(&self) -> PeerID
pub fn send(&mut self, channel_id: u8, packet: &Packet) -> Result<(), PeerSendError>
pub fn disconnect(&mut self, data: u32)        // graceful; Event::Disconnect later
pub fn disconnect_now(&mut self, data: u32)    // immediate, NO event generated
pub fn disconnect_later(&mut self, data: u32)  // after queued packets flush
pub fn state(&self) -> PeerState               // Connected, Disconnected, ...
pub fn connected(&self) -> bool
pub fn round_trip_time(&self) -> Duration      // mean reliable-packet RTT
pub fn round_trip_time_variance(&self) -> Duration
pub fn packet_loss(&self) -> u32               // ratio scaled by PEER_PACKET_LOSS_SCALE
pub fn set_ping_interval(&mut self, ping_interval: u32)        // ms
pub fn set_timeout(&mut self, limit: u32, minimum: u32, maximum: u32)  // 0,0,0 = ENet defaults
pub fn set_mtu(&mut self, mtu: u16) -> Result<(), BadParameter>
pub fn address(&self) -> Option<S::Address>
```

The `data: u32` in `connect`/`disconnect` round-trips to the remote `Event::Connect`/`Disconnect`
— useful for a protocol-version byte (D7) or disconnect reason codes.

> ⚠️ **PeerID reuse:** `PeerID` is an index into the host's peer table; after a disconnect the
> slot is recycled for the next connection. Map `PeerID → entity/session` on `Connect` and clear
> it on `Disconnect`; never treat a stored `PeerID` as a stable identity.

Features: `default = ["std"]`. No async, no tokio — exactly matches D8's no-async-in-hot-loop.

---

## 2 — `godot` crate 0.5.x (gdext) — client extension

Official godot-rust GDExtension binding. Latest: **0.5.3** (2026-05-19). godot-rust 0.4+ requires
Godot ≥ 4.2; feature flags `api-4-2` … `api-4-6` select the API level. Default = the current
minor release. Rule: an extension compiled against API `X` runs on any Godot ≥ `X`, never older.
For this project pin **`api-4-6`** (we control the runtime — it is Godot 4.6).

### Crate setup (`rust/client_ext/Cargo.toml`)

```toml
[package]
name = "client_ext"
version = "0.1.0"
edition = "2021"

[lib]
crate-type = ["cdylib"]            # dynamic C library Godot can load

[dependencies]
godot = { version = "0.5", features = ["api-4-6"] }
protocol = { path = "../protocol" }
sim_core = { path = "../sim_core" }
```

### Entry point

```rust
use godot::prelude::*;

struct OmegaClientExt;

#[gdextension]
unsafe impl ExtensionLibrary for OmegaClientExt {}
```

This generates the `gdext_rust_init` symbol that the `.gdextension` file names.

### `.gdextension` file

Book template (hello-world chapter):

```ini
[configuration]
entry_symbol = "gdext_rust_init"
compatibility_minimum = 4.1
reloadable = true

[libraries]
linux.debug.x86_64 =     "res://../rust/target/debug/lib{YourCrate}.so"
linux.release.x86_64 =   "res://../rust/target/release/lib{YourCrate}.so"
windows.debug.x86_64 =   "res://../rust/target/debug/{YourCrate}.dll"
windows.release.x86_64 = "res://../rust/target/release/{YourCrate}.dll"
macos.debug =            "res://../rust/target/debug/lib{YourCrate}.dylib"
macos.release =          "res://../rust/target/release/lib{YourCrate}.dylib"
```

`compatibility_minimum` must be ≥ the API level compiled against — with `api-4-6` it must be
**`4.6`**. Concrete file for this repo at `client/bin/omega_client_ext.gdextension`
(see [Workspace layout](#workspace-layout)).

### Registering a class GDScript can `new()`

`#[derive(GodotClass)]` auto-registers the class at load. With no `base` key the base defaults to
`RefCounted`; `#[class(init)]` generates the constructor so GDScript's `MyClass.new()` works.

```rust
use godot::prelude::*;

#[derive(GodotClass)]
#[class(init, base=RefCounted)]          // RefCounted is also the default base
pub struct NetCodec {
    base: Base<RefCounted>,
}

#[godot_api]
impl NetCodec {
    /// GDScript: var bytes := codec.encode_input(tick, dir, buttons)
    #[func]
    fn encode_input(&self, tick: i64, move_dir: Vector2, buttons: i64) -> PackedByteArray {
        let bytes: Vec<u8> = protocol::encode_input(tick as u32, move_dir.x, move_dir.y, buttons as u8);
        PackedByteArray::from(bytes.as_slice())
    }

    /// GDScript: var snap: Dictionary = codec.decode_snapshot(peer.get_packet())
    #[func]
    fn decode_snapshot(&mut self, bytes: PackedByteArray) -> Dictionary {
        let raw: &[u8] = bytes.as_slice();             // zero-copy view
        let snap = protocol::decode_snapshot(raw);
        let mut dict = Dictionary::new();
        dict.set("tick", snap.tick as i64);
        // entities as an Array of Dictionaries, or flat packed arrays for speed
        dict
    }
}
```

GDScript side — global class, no preload needed once the extension loads:

```gdscript
var codec := NetCodec.new()
var bytes: PackedByteArray = codec.encode_input(tick, input_dir, buttons)
```

For a `sim_core` prediction step, same pattern (`#[func] fn step(&mut self, ...)`), or a static
constructor when custom args are needed (`MonsterConfig.new()` would bypass it):

```rust
#[godot_api]
impl PredictionSim {
    #[func]
    fn create(arena_half_extent: f32) -> Gd<Self> {
        Gd::from_init_fn(|base| Self { base, world: sim_core::World::new(arena_half_extent) })
    }
}
```

### Marshalling cheat sheet (`#[func]` params / returns)

| GDScript | Rust | Notes |
|---|---|---|
| `PackedByteArray` | `PackedByteArray` | `as_slice() -> &[u8]`, `to_vec()`, `PackedByteArray::from(&[u8])`, `extend_from_slice` |
| `Vector2` / `Vector2i` | `Vector2` / `Vector2i` | by value, `f32` components (single-precision build) |
| `int` | `i64` (also `i32`, `u16`… with range checks) | GDScript int is 64-bit |
| `float` | `f64` (and `f32`) | |
| `String` | `GString` | |
| `Dictionary` | `Dictionary` (`vdict!`, typed `dict!`) | reference-semantics; `clone()` shares |
| `Array` | `VariantArray` / `Array<T>` (`varray!`, `iarray!`) | reference-semantics |
| object | `Gd<T>` | |

Crossing the GDScript↔native boundary has per-call cost — prefer **one call per packet/tick with
a `PackedByteArray`** over chatty per-field calls (this is why D6 hands raw bytes across).

---

## 3 — Godot 4.6 `ENetConnection` (GDScript client transport)

### Create + connect (3 channels per the D2 plan)

```gdscript
var connection := ENetConnection.new()
var server_peer: ENetPacketPeer

func connect_to_server(host: String, port: int) -> void:
    # create_host(max_peers = 32, max_channels = 0, in_bandwidth = 0, out_bandwidth = 0)
    connection.create_host(1)                                  # client: 1 peer (the server)
    server_peer = connection.connect_to_host(host, port, 3)    # request 3 channels
```

`create_host` binds a random dynamic UDP port (server-style binding is `create_host_bound`).
ENet negotiates the channel count at connect to the **min** of both sides — the server's
`channel_limit: 3` and the client's `channels = 3` must agree. `connect_to_host`'s `data: int`
arg surfaces as `data` in the server's `Event::Connect` (protocol-version slot).

### Event polling loop

`service(timeout=0)` is non-blocking and returns a 4-element Array:
`[EventType, ENetPacketPeer, data: int, channel: int]`.
EventType: `EVENT_ERROR = -1`, `EVENT_NONE = 0`, `EVENT_CONNECT = 1`, `EVENT_DISCONNECT = 2`,
`EVENT_RECEIVE = 3`. On `EVENT_RECEIVE`, read the bytes from the **peer**, channel from index 3:

```gdscript
func _process(_delta: float) -> void:
    while true:
        var ev: Array = connection.service(0)
        match ev[0]:
            ENetConnection.EVENT_NONE:
                break
            ENetConnection.EVENT_CONNECT:
                _on_connected(ev[1])                 # ev[3] holds peer data
            ENetConnection.EVENT_DISCONNECT:
                _on_disconnected()
            ENetConnection.EVENT_RECEIVE:
                var peer: ENetPacketPeer = ev[1]
                var channel: int = ev[3]
                var bytes: PackedByteArray = peer.get_packet()   # PacketPeer API
                _on_packet(channel, bytes)           # → hand to NetCodec (Rust)
            ENetConnection.EVENT_ERROR:
                push_error("ENet host error — destroy and recreate")
                break
```

Call this every frame; "Call this function regularly to handle connections, disconnections, and
to receive new packets" (class doc).

### Sending — `ENetPacketPeer.send(channel, packet, flags)`

Flag constants: `FLAG_RELIABLE = 1`, `FLAG_UNSEQUENCED = 2`, `FLAG_UNRELIABLE_FRAGMENT = 8`.

**Unreliable-sequenced is `flags = 0`** — there is no explicit flag for it. ENet's default
unreliable mode is channel-sequenced; `FLAG_UNSEQUENCED` *removes* sequencing (out-of-order
dispatch allowed). Verified against the rusty_enet 0.4.0 source: `Unreliable { sequenced: true }`
encodes to flag value `0`. So:

```gdscript
server_peer.send(2, input_bytes, 0)                            # ch2 PLAYER_INPUT — unreliable SEQUENCED
server_peer.send(1, event_bytes, ENetPacketPeer.FLAG_RELIABLE) # ch1 — reliable ordered
# never FLAG_UNSEQUENCED on ch0/ch2 — that allows stale-after-newer dispatch
# FLAG_UNRELIABLE_FRAGMENT only if a packet may exceed MTU (1392) and must NOT upgrade to reliable
```

### RTT / timeouts / teardown

```gdscript
var rtt_ms: float = server_peer.get_statistic(ENetPacketPeer.PEER_ROUND_TRIP_TIME)
var loss: float   = server_peer.get_statistic(ENetPacketPeer.PEER_PACKET_LOSS)  # /PACKET_LOSS_SCALE
server_peer.set_timeout(limit_ms, min_ms, max_ms)
server_peer.ping_interval(interval_ms)
server_peer.peer_disconnect(0)        # graceful; also peer_disconnect_later / peer_disconnect_now
connection.flush()                    # force queued packets out (e.g. right before quit)
connection.destroy()
```

This replaces today's app-level `HEARTBEAT` RTT plumbing (D2: relocate the clock-sync payload only).

**Compression:** `connection.compress(mode)` defaults to `COMPRESS_NONE` — do **not** call it
(server has no compressor). Doc warning: "The compression mode must be set to the same value on
both the server and all its clients." **DTLS:** `dtls_client_setup` exists — do not use;
rusty_enet has no DTLS.

---

## 4 — Supporting crates (Ed25519, HTTP, tracing, metrics)

### Ed25519 ticket verification — `ed25519-dalek` v2 (D9)

v2.2.0. Go's `crypto/ed25519` (RFC 8032) signatures verify directly. Constants
`PUBLIC_KEY_LENGTH = 32`, `SIGNATURE_LENGTH = 64`.

```rust
use ed25519_dalek::{Signature, Verifier, VerifyingKey};

let key = VerifyingKey::from_bytes(&pub_bytes_32)?;   // distribute via env/secret (D9)
let sig = Signature::from_bytes(&sig_bytes_64);       // infallible for [u8; 64]
// or from a slice: Signature::try_from(&sig_bytes[..])?
key.verify_strict(ticket_payload, &sig)?;             // reject ⇒ refuse CONNECT_AUTH
```

Use **`verify_strict`** (rejects malleable/small-order-component signatures); we control both
ends, so the stricter check costs nothing. Verification is ~50 µs — fine inline in the tick on a
join, no offload needed.

### HTTP client for Go API calls — `ureq` 3.x (recommended) over `reqwest`

D8 forbids an async runtime in the hot loop. `ureq` is **purely blocking I/O, no tokio anywhere**
(reqwest's `blocking` mode still spins an internal tokio runtime). Persistence calls (D10
hydrate/death-save) run on a dedicated I/O thread talking to the tick thread over channels;
`ureq::Agent` is the per-thread client with connection reuse.

```rust
use std::time::Duration;
use ureq::Agent;

let agent: Agent = Agent::config_builder()
    .timeout_global(Some(Duration::from_secs(5)))
    .build()
    .into();

// GET
let body: String = agent.get("http://api:8080/healthz").call()?.body_mut().read_to_string()?;

// POST JSON (feature "json"; idempotent absolute-state save per D10)
let resp: SaveAck = agent
    .post("http://api:8080/internal/characters/save")
    .header("Authorization", &server_token)
    .send_json(&save_payload)?            // serde::Serialize
    .body_mut()
    .read_json::<SaveAck>()?;             // serde::Deserialize
```

4xx/5xx surface as `Err(ureq::Error)` by default — the death-save retry loop must treat them
explicitly (retry on 5xx/transport, never on 4xx).

### Tracing + Prometheus (D13 observability)

`tracing` + `tracing-subscriber` for structured logs; `metrics` facade +
`metrics-exporter-prometheus` for the `/metrics` endpoint.

```rust
tracing_subscriber::fmt()
    .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
    .init();

use metrics::{counter, gauge, histogram};
use metrics_exporter_prometheus::PrometheusBuilder;

PrometheusBuilder::new()
    .with_http_listener(([0, 0, 0, 0], 9100))
    .install()?;                                    // see note below

counter!("snapshots_sent_total").increment(1);
gauge!("players_online").set(world.player_count() as f64);
histogram!("tick_duration_ms").record(tick_elapsed_ms);
```

**Note on D8 purity:** `PrometheusBuilder::install()` spawns its exporter on "a new background
thread … which a Tokio single-threaded runtime is launched on" (when not already in a runtime).
That runtime is confined to the exporter thread — the tick thread stays sync, so this honors the
*spirit* of D8 ("a small runtime/thread only for" side I/O). If a strictly tokio-free binary is
wanted, the fallback is the `prometheus` crate + a hand-rolled `tiny_http` responder; not
recommended (more code for less).

The `metrics` macros are lock-free atomics at the call site — safe to call inside the tick loop.

---

## Wire-compat risks

1. **Version alignment is exact — keep it that way.** Godot master/4.6 bundles ENet **1.3.18
   commit `2662c0d`** (`thirdparty/README.md`); rusty_enet 0.4 is transpiled from **the same
   commit**. Godot's fork adds only a socket layer (`enet_godot.cpp` — IPv6 + DTLS via Godot's
   NetSocket); the *protocol* code is untouched, so plain-UDP ENet is wire-compatible with stock
   ENet — and with rusty_enet. Re-verify the bundled version if the client engine ever upgrades.
2. **Checksum/compressor must stay `None`/`COMPRESS_NONE`.** Verified in Godot's
   `enet_connection.cpp`: Godot never sets `host->checksum`, and compression defaults to none.
   rusty_enet defaults match. **But the rusty_enet bundled examples enable
   `RangeCoder` + `crc32`** — copying those `HostSettings` verbatim makes every Godot connect
   attempt fail at the first packet. Use `..Default::default()`.
3. **Unreliable > MTU silently upgrades to reliable** (both sides, by ENet design; MTU default
   1392). A fat ch0 snapshot becomes reliable-fragmented → head-of-line blocking returns exactly
   where D2 tried to kill it. Enforce the per-peer snapshot byte budget < ~1300 B, or send
   `always_unreliable` / `FLAG_UNRELIABLE_FRAGMENT`.
4. **Unreliable-sequenced has no flag** — it's `flags = 0` in Godot and
   `Packet::unreliable` in Rust. `FLAG_UNSEQUENCED` is a *different*, wrong mode for ch0/ch2
   (permits out-of-order dispatch). Easy to get backwards.
5. **Channel count is negotiated to the min at connect.** Client must pass `channels = 3` in
   `connect_to_host` and the server `channel_limit: 3`; a send on a channel ≥ negotiated count
   fails silently-ish (`PeerSendError`). Assert channel count on `Event::Connect`.
6. **DTLS off.** rusty_enet has no DTLS; never call `dtls_client_setup` client-side.
7. **rusty_enet maturity.** README self-assessment: "this project couldn't be much further from
   'ready for serious use'" (transpilation-bug risk). Mitigation per D2/D14: pin `=0.4.0`,
   golden-test the Godot↔Rust handshake + all three channel modes in M0, keep the bot swarm on
   real ENet traffic for soak.
8. **Master-branch docs mismatch** (see §1 warning): API examples on GitHub differ from 0.4.0.
9. **PeerID slots are recycled** after disconnect — map to session identity on Connect, clear on
   Disconnect (risk of sending a dead player's snapshots to a fresh connection otherwise).
10. **`disconnect_now` emits no local event** — server-initiated kicks must do their own cleanup.

## Recommended crate pins

```toml
# rust/Cargo.toml  [workspace.dependencies]
rusty_enet = "=0.4.0"            # exact pin: pre-1.0, master already API-incompatible (D2 risk note)
godot = { version = "0.5.3", features = ["api-4-6"] }   # client_ext only; Godot ≥ 4.6 runtime
ed25519-dalek = "2.2"            # verify-only on the server (no rand_core feature needed)
ureq = { version = "3.3", features = ["json"] }         # blocking; no tokio (D8)
serde = { version = "1", features = ["derive"] }
serde_json = "1"
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter"] }
metrics = "0.24"
metrics-exporter-prometheus = "0.18"
# optional: slotmap = "1" for the D8 typed arenas
```

(Latest as of 2026-06-11: rusty_enet 0.4.0 · godot 0.5.3 · ed25519-dalek 2.2.0 · ureq 3.3.0 ·
metrics 0.24.6 · metrics-exporter-prometheus 0.18.3 · tracing 0.1.44 · tracing-subscriber 0.3.23.)

## Workspace layout

```
rust/
├── Cargo.toml                # [workspace] members = ["protocol", "sim_core", "server", "client_ext"]
├── protocol/                 # D7: packet structs + hand-rolled bit codec; PROTOCOL_VERSION const
│   └── src/lib.rs            #     no_std-friendly, zero deps ideally; property-tested round-trips
├── sim_core/                 # D5: movement/collision/dash/knockback/stamina + HitAuthority predicates
│   └── src/lib.rs            #     pure logic, NO godot dep (linked by both server and client_ext)
├── server/                   # D8: bin — rusty_enet host, 30 Hz tick thread, ureq I/O thread,
│   └── src/main.rs           #     ed25519 verify, tracing + metrics
└── client_ext/               # D6: cdylib — gdext; exposes NetCodec + prediction sim to GDScript
    └── src/lib.rs
```

Dependency edges: `server → {protocol, sim_core, rusty_enet, …}`;
`client_ext → {protocol, sim_core, godot}`; `protocol`/`sim_core` depend on nothing Godot- or
network-related. `godot` and `rusty_enet` never meet in one crate.

### `.gdextension` for this repo — `client/bin/omega_client_ext.gdextension`

```ini
[configuration]
entry_symbol = "gdext_rust_init"
compatibility_minimum = 4.6
reloadable = true

[libraries]
macos.debug =            "res://bin/macos/libclient_ext.dylib"
macos.release =          "res://bin/macos/libclient_ext.dylib"
macos.debug.arm64 =      "res://bin/macos/libclient_ext.dylib"
macos.release.arm64 =    "res://bin/macos/libclient_ext.dylib"
linux.debug.x86_64 =     "res://bin/linux/libclient_ext.so"
linux.release.x86_64 =   "res://bin/linux/libclient_ext.so"
windows.debug.x86_64 =   "res://bin/windows/client_ext.dll"
windows.release.x86_64 = "res://bin/windows/client_ext.dll"
```

Artifacts are **copied into the Godot project** (not referenced via `res://../rust/target/…` as
in the book's dev setup) so exports pick them up without a Rust toolchain on the export machine —
mirroring the D4-era "client builds with no Rust toolchain" convention. Copy step,
`scripts/build_client_ext.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../rust"
cargo build -p client_ext --release
mkdir -p ../client/bin/macos
cp target/release/libclient_ext.dylib ../client/bin/macos/
# cross-builds (CI): linux x86_64 → client/bin/linux/, windows x86_64 → client/bin/windows/
```

Add `client/bin/*/` to the export presets' include filters if non-resource files are filtered.
During day-to-day sim iteration, `reloadable = true` lets the editor pick up a rebuilt dylib on
focus; a debug-profile copy step (same script, `--release` dropped) keeps iteration fast.

## See also

- [`../migration-spec.md`](../migration-spec.md) — D2 (transport/channels), D5–D8 (sim_core,
  extension scope, protocol crate, tick architecture), D9 (Ed25519), D13 (observability).
- [`../../adr/0003-enet-udp-transport.md`](../../adr/0003-enet-udp-transport.md) — why ENet.
- docs.rs/rusty_enet/0.4.0 · godot-rust.github.io/book · docs.godotengine.org `ENetConnection` /
  `ENetPacketPeer`.
