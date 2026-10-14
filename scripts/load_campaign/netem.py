"""Selective, seeded per-direction impairment; administrative traffic stays in band 1."""
import shlex
import run

PROFILES = {
    "delay25": (25, 0, 0), "delay50": (50, 0, 0), "delay100": (100, 0, 0),
    "jitter5": (50, 5, 0), "jitter20": (50, 20, 0),
    "loss0.1": (0, 0, .1), "loss1": (0, 0, 1), "loss3": (0, 0, 3), "combined": (50, 20, 1),
}
RESTORE = "sudo -n tc qdisc replace dev eth0 root fq_codel limit 10240 flows 1024 quantum 1514 target 5ms interval 100ms memory_limit 33554432 ecn"


def cleanup_unit(run_id, role):
    return run.UNIT_PREFIX + 'netem-cleanup-' + run_id + '-' + role


def restore(role):
    run.ssh(role, RESTORE)


def apply(role, profile, seed, run_id, timeout):
    delay, jitter, loss = PROFILES[profile]
    other = run.HOSTS["bots" if role == "game" else "game"]["ipv4"]
    match = "src_port 8081" if role == "game" else "dst_port 8081"
    netem = "limit 200000"
    if delay:
        netem += f" delay {delay}ms"
        if jitter:
            netem += f" {jitter}ms distribution normal"
    if loss:
        netem += f" loss random {loss}%"
    netem += f" seed {seed}"
    directory = run.REMOTE + "/" + run_id + "/" + role
    run.ssh(role, f"tc -s -j qdisc show dev eth0 > {directory}/netem-original.json; tc -s -j filter show dev eth0 > {directory}/filters-original.json")
    # A remote fallback also cleans up if the operator-side controller disappears.
    cleanup = "sleep " + str(timeout) + "; " + RESTORE
    run.ssh(role, f"sudo -n systemd-run --quiet --unit={cleanup_unit(run_id, role)} /bin/bash -c " + shlex.quote(cleanup))
    command = (
        "sudo -n tc qdisc replace dev eth0 root handle 1: prio bands 3 priomap " + " ".join(["0"] * 16) + "; "
        "sudo -n tc qdisc add dev eth0 parent 1:1 handle 10: fq_codel limit 10240 flows 1024 quantum 1514 target 5ms interval 100ms memory_limit 33554432 ecn; "
        f"sudo -n tc qdisc add dev eth0 parent 1:2 handle 20: netem {netem}; "
        f"sudo -n tc filter add dev eth0 protocol ip parent 1: prio 10 flower skip_hw ip_proto udp dst_ip {other}/32 {match} classid 1:2; "
        f"tc -s -j qdisc show dev eth0 > {directory}/netem-applied.json; tc -s -j filter show dev eth0 parent 1: > {directory}/filters-applied.json"
    )
    run.ssh(role, "set -e; " + command)
    return {"delay_ms": delay, "jitter_ms": jitter, "loss_percent": loss, "seed": seed, "queue_limit_packets": 200000}
