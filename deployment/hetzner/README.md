# Temporary Hetzner load-test hosts

Use these artifacts for the isolated Arena / bot-generator experiment described in
[the host-selection and setup note](../../docs/ops/hetzner-load-testing.md).
The user has created separate CAX11 game and bot hosts in Falkenstein, both on Ubuntu
26.04.1 LTS / aarch64. Runtime setup uses the server's unsigned dev mode because there is
no API host; UDP game access is restricted to the operator and bot IPs. Current connection
details are in ignored `access.local.json`. CCX13 comes later, after CAX11 stabilization:
[the deferred comparison task](https://github.com/Operatorr/godot-networking-poc/issues/34).

The game service is running, and the separate bot host passed a three-bot / 30-second
movement smoke test with seed 29: all three connected, received Snapshots, and had no
decode/send errors. Raw evidence is in ignored `results/smoke-20261013/`. Both binaries
use commit `89348a21dcc3ce190aa851bb5f2cb49256097297` and Rust 1.95.0. This verifies setup;
the capacity and latency sweeps are still pending.

## Before creating each server

1. Select **Ubuntu 24.04 LTS** in OS Images (use the Ubuntu version dropdown). Use the same
   OS version on CCX13, CAX11, and any bot host. This matches the current native deployment.
   If 24.04 is unavailable, use 26.04 LTS consistently and record that change.
2. Enable Primary IPv4 and IPv6. Choose the same available EU location for all hosts.
3. In SSH keys, add the complete contents of
   [`ssh/omega_loadtest_ed25519.pub`](ssh/omega_loadtest_ed25519.pub), name it
   `omega-loadtest-2026-10`, and select it for each server. One public key can be used on
   every test host. On the Mac, from the repo root:

   ```bash
   pbcopy < deployment/hetzner/ssh/omega_loadtest_ed25519.pub
   ```

   The corresponding **private** key is `deployment/hetzner/ssh/omega_loadtest_ed25519`.
   It stays on this computer with mode 0600 and is ignored by Git. It is deliberately
   unencrypted for this temporary unattended test workflow. Upload only the `.pub` file.
   The SSH public-key fingerprint is:

   ```text
   SHA256:UtC5Y6VWbIrptSdUyOFCyoWWhMPgwO8BeJVVC3nVkMg
   ```

4. Paste all of [`cloud-init.yaml`](cloud-init.yaml) into **Cloud config** on each host:

   ```bash
   pbcopy < deployment/hetzner/cloud-init.yaml
   ```

   This creates the `deploy` user with the public key and passwordless sudo, disables
   SSH password authentication, installs build/measurement tools, and installs **Rust
   1.95.0** for the host architecture. Root key access remains available for bootstrap
   recovery. Game/bot builds and runtime services are configured over SSH afterward.
   No application secrets or private keys are embedded in user-data. The same file works
   for the x86 and ARM Ubuntu hosts.
5. Leave **Volumes** and **Backups** off. The included disks are sufficient for these
   temporary builds and results; export results before destroying the hosts.
6. Create and attach the free Cloud Firewalls below. Their optional local JSON definitions
   are in the ignored `firewall.local.json`, using the operator's detected public IPv4
   `/32` from `access.local.json`. Check that this is still the address used for SSH.

## Firewall rules

Leave outbound rules empty: outbound is permitted by default. Unmatched inbound traffic
is denied. [Hetzner firewall behavior](https://docs.hetzner.com/cloud/firewalls/overview/).

| Host role | Direction | Protocol / port | Source |
| --- | --- | --- | --- |
| All hosts | Inbound | TCP 22 | Operator's current public IPv4 `/32` |
| Game hosts | Inbound | UDP 8081 | Operator IPv4 `/32` for PC bots; add the bot VPS IPv4 `/32` after creation |
| All hosts | Inbound | ICMP | Any IPv4/IPv6, for diagnostics and path MTU |

Use a game firewall for the game host, and a separate SSH/ICMP-only firewall for a bot
host. ENet replies to the bot host use the stateful return path; it needs no public game
listener. Keep metrics port 9100 private and access it through an SSH tunnel. If the home
IP changes, update the firewall sources before reconnecting. A blank firewall attached to
a server blocks SSH, so add the rules before attachment.

## What to send after creation

Send the **public IPv4, name/role, plan, and location** for each host, and whether this
cloud-init and the uploaded key were selected. For example:

```text
ccx-game: <IPv4>, CCX13, Falkenstein
arm-game: <IPv4>, CAX11, Falkenstein
bots:     <IPv4>, CCX13, Falkenstein  # optional; otherwise bots on personal computer
Cloud config and omega-loadtest-2026-10 key applied to all hosts.
```

With those details the local key can be used to connect as `deploy`. No password or
Hetzner API token is needed for SSH provisioning. Managing cloud firewalls/resources via
API would separately require a local API credential; using the Console avoids that.
Keep real connection details in the ignored `access.local.json`.

Setup verifies cloud-init, freezes the same repo commit on both hosts, builds the game/bot
binaries, installs the isolated game service, restricts host firewall access, and runs a
three-bot dev-mode smoke test before the load sweep. The game-only
[systemd unit](omega-loadtest-arena.service) reads `/etc/omega-loadtest/arena.json`, serves
UDP 8081, and exports metrics on loopback port 9100. It runs without API/database services.
The bot host also installs [file-descriptor limits](omega-loadtest-limits.conf) in
`/etc/security/limits.d/90-omega-loadtest.conf`: soft 8192, hard 65536, for new `deploy`
login sessions. Each bot needs its own socket.

**Optional future signed-auth testing:** the user confirmed that the former combined
DigitalOcean API/game host no longer exists. Current dev-mode tests do not need API
credentials. If an API is provisioned later, make its `LOAD_TEST_TICKET_SECRET` and public
verification key
available locally. Copy [`auth.local.env.example`](auth.local.env.example) to
`deployment/hetzner/auth.local.env`, set mode 0600, and fill the placeholders there.
This file is ignored by Git. The API private signing key is not needed. The bot secret
goes only to the generator; game hosts receive only the verification public key.
The template is for that future signed path; leave it unused for current unsigned runs.

From the repository root, initial access is:

```bash
ssh -i deployment/hetzner/ssh/omega_loadtest_ed25519 -o IdentitiesOnly=yes deploy@SERVER_IPV4
sudo cloud-init status --wait --long
rustc --version
```

Wait for successful cloud-init completion before builds or benchmarking. If its package
or Rust installation fails, inspect `/var/log/cloud-init-output.log` and fix the bootstrap
over SSH. Root key access is available as a fallback using the same identity.

The YAML has been validated against upstream cloud-init 24.1 and current schemas, its
installer command has passed a Bash syntax check, and the public/private keypair and
private-key ignore rule were verified locally. Both current hosts report successful
cloud-init completion and have the pinned Rust tools installed.
[cloud-init reference](https://docs.cloud-init.io/en/24.1/reference/modules.html),
[Hetzner user-data support](https://docs.hetzner.com/cloud/servers/faq/).

## After the experiment

Export reports/counters, delete the temporary servers and unused chargeable Primary IPv4s,
and remove the uploaded test key from the Hetzner project when it is no longer needed.
Retain the local private key only while access to a test host is still required. Do not
force-add it to Git or place it on the servers.
