# Omega Realm Load Testing

Python-based load testing infrastructure for validating the Omega Realm game server under concurrent player load.

## Setup

```bash
cd load_testing
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Quick Start

Run against a local game server on default port (8081):

```bash
# Baseline test: 50 bots, 2 minutes
python bot_swarm.py --scenario baseline

# Target load: 100 bots, 5 minutes
python bot_swarm.py --scenario target

# Stress test: 200 bots, 5 minutes
python bot_swarm.py --scenario stress
```

## Custom Tests

```bash
# Custom bot count and duration
python bot_swarm.py --bots 75 --duration 180 --server ws://localhost:8081

# Remote server
python bot_swarm.py --scenario target --server ws://your-server.com:8081

# Verbose logging
python bot_swarm.py --scenario baseline -v

# Custom output file
python bot_swarm.py --scenario target --output my_report.json
```

## CLI Options

| Flag | Description | Default |
|------|-------------|---------|
| `--server`, `-s` | Game server WebSocket URL | `ws://localhost:8081` |
| `--bots`, `-b` | Number of bots to spawn | Scenario default or 50 |
| `--duration`, `-d` | Test duration in seconds | Scenario default or 120 |
| `--scenario` | Predefined scenario (baseline/target/stress) | None |
| `--stagger` | Milliseconds between bot connections | 100 |
| `--output`, `-o` | JSON report output path | `report_<timestamp>.json` |
| `--verbose`, `-v` | Enable debug logging | Off |

## Success Criteria

The load test validates these metrics (from the epic brief):

| Metric | Target |
|--------|--------|
| Server tick rate | > 30 Hz |
| Average latency | < 100ms |
| P95 latency | < 150ms |
| Bandwidth per player | < 5 KB/s |
| Packet loss | < 2% |
| Bot crash rate | < 5% |

## Output

The test generates:
- **Console report** with pass/fail for each criterion
- **JSON report** with detailed per-bot metrics for analysis

## Architecture

Each bot:
1. Connects via WebSocket and sends `CONNECT_AUTH`
2. Sends randomized `PLAYER_INPUT` at 10 Hz
3. Sends `HEARTBEAT` at 1 Hz and measures RTT from echo
4. Parses `STATE_UPDATE` headers to track server tick cadence
5. Detects packet loss from tick sequence gaps
