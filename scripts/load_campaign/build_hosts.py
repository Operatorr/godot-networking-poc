#!/usr/bin/env python3
"""Build a pinned measurement worktree without altering the original handoff checkout."""
import concurrent.futures
import json
import subprocess
import run

revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=run.ROOT, text=True).strip()


def build(role):
    package = "omega-server" if role == "game" else "omega-load-test"
    script = f"""set -eu
cd /home/deploy/omega-realm
git fetch origin measure/cax11-20261013
if test -d /home/deploy/omega-measured; then
    test -z "$(git -C /home/deploy/omega-measured status --porcelain)"
    git -C /home/deploy/omega-measured checkout --detach {revision}
else
    git worktree add --detach /home/deploy/omega-measured {revision}
fi
cd /home/deploy/omega-measured/rust
source /home/deploy/.cargo/env
cargo build --release --locked -j 2 -p {package} > {run.REMOTE}/{role}-measurement-build.log 2>&1
sha256sum target/release/{package}
git rev-parse HEAD
rustc -Vv
"""
    output = run.ssh(role, script)
    (run.RAW / (role + "-measurement-build.txt")).write_text(output)
    run.copy(role, run.REMOTE + "/" + role + "-measurement-build.log", run.RAW / (role + "-measurement-build.log"), download=True)
    print(role + " measurement build complete", flush=True)


with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    list(pool.map(build, run.HOSTS))
run.install()
