# Omega Realm — Client Distribution & Testing

**Status:** As-built reality (Phase 1).
**Scope:** how to *test*, *build*, and *ship* the **game client** (the Godot project under
`client/`). For **server** deploy (the Rust game servers + Go API) see
[`infrastructure.md`](infrastructure.md) and the step-by-step runbook
[`../../deployment/DEPLOYMENT.md`](../../deployment/DEPLOYMENT.md).

> The client is the only thing players run. It is built on a **developer laptop** (Godot 4.6 +
> export templates) and handed to players — the droplet never builds, hosts, or runs the client
> (`NetworkManager` refuses headless/server mode). There is **no automated distribution** yet
> (no CDN / itch / Steam) — see [Known gap](#known-gap).

---

## 1. Testing — run from the Godot editor

You do **not** need an export to test. The editor runs the project source directly, so any
GDScript change is live the moment you press Play. Reach for `build_client.sh` only when handing a
binary to someone without Godot.

```bash
cd client && godot --path . .        # or just press Play (F5) in the editor
```

**Pointing the client at a stack** — the login screen has a **"Use local server (dev)"** checkbox,
backed by `use_local_api` in `UserPreferences` (persisted to `user://preferences.json`):

| Toggle | API target | Use when |
|---|---|---|
| **OFF** (default) | `ClientConfig.production_api_base_url` → `https://gsapi.marrowtech.app` | Testing against the **live** stack |
| **ON** | `local_api_base_url` → `http://localhost:8080` | Testing against a local `dev_local.sh` stack |

The client only knows the **API** URL directly; the **game-server** address comes back from the
API's `GET /api/regions` (region select → heartbeat-advertised connect address). So flipping the
toggle re-points both the account API *and*, indirectly, which game server you land on.

**Auth note (M3 tickets).** Editor vs. export does not change the auth path: the client always
fetches a signed session ticket from whichever API it targets
([`server/design.md`](../server/design.md) §auth). So before an editor test against **live**, the
live keys must already be set (next section) — otherwise the API returns 503, the client joins
unsigned, and the fail-closed server rejects it (`AuthResult` code 2 → reconnect loop).

> Local signed-ticket testing is possible but more setup: run the local API with
> `OMEGA_TICKET_PRIVKEY` and the local server with the matching `OMEGA_TICKET_PUBKEY` **without**
> `--allow-unsigned-tickets`. The default `dev_local.sh` passes `--allow-unsigned-tickets`, so it
> skips the signed path entirely — fine for gameplay testing, but it does **not** exercise M3.

---

## 2. Building the client (laptop)

Requires **Godot 4.6** on `PATH` and the export templates installed. The built **GDExtension**
(`client/bin/…`) is committed, so a plain export needs no Rust toolchain — rebuild it only after
`rust/` changes.

```bash
./scripts/build_client_ext.sh    # Rust GDExtension → client/bin/{macos,linux,windows}/  (only after rust/ changes)
./scripts/build_client.sh        # Godot export → exports/client/{windows,linux,macos}/
```

`build_client.sh` exports three presets — `Windows Desktop (Client)`,
`Linux Desktop (Client)`, `macOS (Client)` (`client/export_presets.cfg`) — to:

| Platform | Output |
|---|---|
| Windows | `exports/client/windows/omega-client.exe` |
| Linux | `exports/client/linux/omega-client.x86_64` |
| macOS | `exports/client/macos/omega-client.app` |

> **macOS GDExtension gotcha:** `build_client_ext.sh` `rm`s `libclient_ext.dylib` before copying —
> overwriting in place keeps the old inode and dyld SIGKILLs on the stale code-signature cache.
> Don't hand-copy the dylib over an existing one.

---

## 3. Player-facing deploy runbook (M3 signed tickets)

A player-facing release is **fail-closed**: the client presents a signed ticket and the server
verifies it. Set the keypair once, then ship the client. The Ed25519 key steps live in the server
runbook ([`../../deployment/DEPLOYMENT.md`](../../deployment/DEPLOYMENT.md) §3) — summarized here for
the end-to-end picture:

1. **Generate one keypair** (laptop): `cd api && go run ./cmd/gen_ticket_key` — prints **two
   different** hex values, a `PRIVKEY` line and a `PUBKEY` line.
2. **Private half → API** (droplet): `/etc/omega-realm/api.env` → `OMEGA_TICKET_PRIVKEY=<privkey line>`
   (activates the `/api/character/ticket` mint endpoint; was returning 503).
3. **Public half → game server** (droplet): `/etc/omega-realm/server.env` →
   `OMEGA_TICKET_PUBKEY=<pubkey line>`, keep `OMEGA_ALLOW_UNSIGNED_TICKETS=false`.
   *Never set `PUBKEY = PRIVKEY`* — they are a matched pair, different values.
4. **Restart** the API + game servers (`./scripts/deploy.sh restart`, or full `deploy.sh` to also
   pick up server code). The API logs `Session-ticket signing ENABLED … OMEGA_TICKET_PUBKEY=<value>`
   — that must equal what you put in `server.env`.
5. **Rebuild + distribute the client** (laptop): `./scripts/build_client.sh`, then hand the new
   binary to players. Players must run the rebuilt client for the ticket-fetch code to take effect.

**Boot guardrail.** If `OMEGA_ALLOW_UNSIGNED_TICKETS=false` and `OMEGA_TICKET_PUBKEY` is empty (or
malformed), the game server **refuses to start** — a server that can admit no one fails loud rather
than stranding every player behind a "Connection Lost, reconnecting" loop (`rust/server/src/main.rs`).

---

## Known gap

There is **no automated client distribution**. `build_client.sh` only drops binaries in
`exports/client/`; getting them to players is currently manual (whatever channel you use). No
auto-update, version gate, or CDN/itch/Steam pipeline exists. If the wire protocol or the M3 auth
flow changes, **players on an old binary silently break** — there is no server-side min-version
check today. Worth building before any real player population.
