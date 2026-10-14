"""Passive pre-qdisc egress observation on a dummy interface; never redirect the flow."""
import run


def apply(role, directory):
    other = run.HOSTS["bots" if role == "game" else "game"]["ipv4"]
    port = "src_port 8081" if role == "game" else "dst_port 8081"
    run.ssh(role, "set -e; "
            "sudo -n ip link add omega-observe type dummy; sudo -n ip link set omega-observe up; "
            "sudo -n tc qdisc add dev eth0 clsact; "
            f"sudo -n tc filter add dev eth0 egress protocol ip pref 31 flower skip_hw ip_proto udp dst_ip {other}/32 {port} action mirred egress mirror dev omega-observe; "
            f"tc -s -j filter show dev eth0 egress > {directory}/mirror-filter.json")


def restore(role):
    run.ssh(role, "sudo -n tc qdisc del dev eth0 clsact 2>/dev/null || true; sudo -n ip link del omega-observe 2>/dev/null || true")
