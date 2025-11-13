# Omega Realm - Infrastructure & Deployment Guide

**Date:** November 2024
**Version:** 1.0
**Target Budget (Beta):** $80-100/month
**Budget Progression:** $20 (Alpha) → $100 (Beta) → $500+ (Production)

---

## Table of Contents

1. [Database Hosting Options](#database-hosting-options)
2. [DigitalOcean Infrastructure Overview](#digitalocean-infrastructure-overview)
3. [Phase 1: Alpha Testing (~$20/month)](#phase-1-alpha-testing-20month)
4. [Phase 2: Beta Testing (~$100/month)](#phase-2-beta-testing-100month)
5. [Phase 3: Production/10k+ (~$2,000+/month)](#phase-3-production10k-2000month)
6. [Multi-Region Architecture](#multi-region-architecture)
7. [Load Balancing Strategy](#load-balancing-strategy)
8. [Player Count Scenarios with Diagrams](#player-count-scenarios-with-diagrams)
9. [Scaling Path & Decision Tree](#scaling-path--decision-tree)
10. [Deployment Procedures](#deployment-procedures)

---

## Database Hosting Options

### Option A: Self-Hosted PostgreSQL on Droplet ✅ RECOMMENDED

**Setup:** PostgreSQL runs on the same droplet as the Go API.

#### When to Use

- **Alpha/Beta testing** (recommended)
- **Early launch** with <1000 concurrent players
- **Budget-constrained** projects
- **Your current situation** ← Perfect fit

---

## DigitalOcean Infrastructure Overview

### Regional Availability

```
DigitalOcean Regions Available:

PRIORITY FOR OMEGA REALM:
├─ Singapore (SGP) - PRIMARY ⭐⭐⭐ (low ping for early testers)
├─ Frankfurt (FRA) - SECONDARY ⭐⭐ (Europe expansion)
└─ San Francisco (SFO) - TERTIARY ⭐⭐ (US-West expansion)
```

---

## Phase 1: Alpha Testing ($20/month)

### Target

- **Players:** 20-30 concurrent
- **Duration:** 4-8 weeks (internal testing)
- **Goal:** Validate core gameplay, server architecture, network code

### Infrastructure Diagram

```
┌─────────────────────────────────────────────┐
│           Alpha Testing Setup               │
│                                             │
│  DigitalOcean Droplet (Singapore)           │
│  2 CPU / 4GB RAM / 80GB SSD - $24/month     │
│                                             │
│  ┌────────────────────────────────────────┐ │
│  │ Godot Headless Game Server             │ │
│  │ ├─ All zones (Forest, Desert, etc.)    │ │
│  │ ├─ Hub cities                          │ │
│  │ └─ Single instance (no sharding)       │ │
│  └────────────────────────────────────────┘ │
│                                             │
│  ┌────────────────────────────────────────┐ │
│  │ Go API Server                          │ │
│  │ ├─ Authentication (JWT)                │ │
│  │ ├─ Character management               │ │
│  │ └─ Tournament/leaderboard              │ │
│  └────────────────────────────────────────┘ │
│                                             │
│  ┌────────────────────────────────────────┐ │
│  │ PostgreSQL (local on droplet)          │ │
│  │ ├─ Users table                         │ │
│  │ ├─ Characters table                    │ │
│  │ └─ Leaderboards table                  │ │
│  └────────────────────────────────────────┘ │
│                                             │
│  ┌────────────────────────────────────────┐ │
│  │ Redis (local on droplet)               │ │
│  │ ├─ Session cache                       │ │
│  │ ├─ Leaderboard cache                   │ │
│  │ └─ Rate limiting                       │ │
│  └────────────────────────────────────────┘ │
│                                             │
└─────────────────────────────────────────────┘
             │
    ┌────────┴─────────┐
    │                  │
    ▼                  ▼
[Dev Client]      [Tester Client]
(Local)           (Remote SSH)
```

### Monitoring (Barebones)

```bash
# Manual monitoring (no cost)
# Game Server FPS
$ ps aux | grep godot

# API health check
$ curl http://localhost:8080/health

# Database check
$ sudo -u postgres psql -c "SELECT version();"

# Redis check
$ redis-cli ping
```

### When to Graduate to Beta

Graduate when you have:

- ✅ Gameplay loop working (character creation, combat)
- ✅ Server stability (99%+ uptime for 1+ week)
- ✅ Network code validated (no sync issues)
- ✅ ~20-30 concurrent players tested simultaneously
- ✅ Ready for external testers

---

## Phase 2: Beta Testing (~$100/month)

### Target

- **Players:** 50-200 concurrent
- **Duration:** 4-12 weeks (closed beta with external testers)
- **Goal:** Balance, bug fixes, stress testing, prepare for launch

### Infrastructure Diagram

```
┌──────────────────────────────────────────────────────────┐
│                   Beta Testing Setup                      │
│                  DigitalOcean (Singapore)                 │
├──────────────────────────────────────────────────────────┤
│                                                            │
│  ┌────────────────────────────────────────────────────┐   │
│  │ Godot Game Server #1 (Zone Server)                │   │
│  │ Droplet: 4 CPU / 8GB RAM - $48/month              │   │
│  │ ├─ Forest + Desert zones                          │   │
│  │ ├─ Hub City instance (50% of capacity)            │   │
│  │ └─ 50-75 concurrent players                       │   │
│  └────────────────────────────────────────────────────┘   │
│                                                            │
│  ┌────────────────────────────────────────────────────┐   │
│  │ Godot Game Server #2 (Zone Server)                │   │
│  │ Droplet: 4 CPU / 8GB RAM - $48/month              │   │
│  │ ├─ Mountain + Volcanic zones                      │   │
│  │ ├─ Hub City instance (50% of capacity)            │   │
│  │ └─ 50-75 concurrent players                       │   │
│  └────────────────────────────────────────────────────┘   │
│                                                            │
│  ┌────────────────────────────────────────────────────┐   │
│  │ Go API Server + Monitoring                        │   │
│  │ App Platform (managed) or Droplet - $24/month     │   │
│  │ ├─ 2 CPU / 4GB RAM                               │   │
│  │ ├─ Character management                           │   │
│  │ ├─ Leaderboards                                   │   │
│  │ └─ Tournament management                          │   │
│  └────────────────────────────────────────────────────┘   │
│                                                            │
│  ┌────────────────────────────────────────────────────┐   │
│  │ Managed PostgreSQL Database                       │   │
│  │ DO Managed: $25/month (separate droplet)          │   │
│  │ ├─ Automated daily backups                        │   │
│  │ ├─ High availability (optional)                   │   │
│  │ └─ 15GB storage included                          │   │
│  └────────────────────────────────────────────────────┘   │
│                                                            │
│  ┌────────────────────────────────────────────────────┐   │
│  │ Redis Cache (managed)                             │   │
│  │ DO Managed: $7/month                              │   │
│  │ ├─ Leaderboard cache                              │   │
│  │ ├─ Session cache                                  │   │
│  │ └─ Rate limiting                                  │   │
│  └────────────────────────────────────────────────────┘   │
│                                                            │
└──────────────────────────────────────────────────────────┘
         │
    ┌────┴────┬──────────┬──────────┐
    │         │          │          │
    ▼         ▼          ▼          ▼
 Tester    Tester    Tester    Tester
 Client    Client    Client    Client
(Multiple locations, Singapore ISP)
```

### When to Graduate to Production

Graduate when you have:

- ✅ Stable server for 4+ weeks straight
- ✅ 100+ concurrent players successfully tested
- ✅ All major bugs fixed
- ✅ Content is balanced (combat feel right)
- ✅ Ready to accept 500+ players simultaneously

---

## Phase 3: Production/10k+ ($2,000+/month)

### Target

- **Players:** 10,000+ concurrent across 3 regions
- **Regions:** Singapore, Frankfurt, US-West
- **Duration:** Ongoing live service
- **Goal:** Global availability, high performance, scalability

### Full Infrastructure Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    PRODUCTION ARCHITECTURE                       │
│                  (10,000+ Concurrent Players)                    │
└─────────────────────────────────────────────────────────────────┘

         ┌─────────────────────────────────────┐
         │   CloudFlare Global CDN             │
         │   (Static assets, DDoS protection)  │
         └─────────────────────────────────────┘
                      ▲    ▲    ▲
        ┌─────────────┘    │    └─────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│ FRANKFURT REGION │ │ SINGAPORE REGION │ │   US-WEST REGION │
│   (Europe)       │ │    (Primary)     │ │    (Americas)    │
├──────────────────┤ ├──────────────────┤ ├──────────────────┤
│                  │ │                  │ │                  │
│ ┌──────────────┐ │ │ ┌──────────────┐ │ │ ┌──────────────┐ │
│ │Load Balancer │ │ │ │Load Balancer │ │ │ │Load Balancer │ │
│ │  (HAProxy)   │ │ │ │  (HAProxy)   │ │ │ │  (HAProxy)   │ │
│ └──────┬───────┘ │ │ └──────┬───────┘ │ │ └──────┬───────┘ │
│        │         │ │        │         │ │        │         │
│  ┌─────┴─────┐   │ │  ┌─────┴─────┐   │ │  ┌─────┴─────┐   │
│  │    API    │   │ │  │    API    │   │ │  │    API    │   │
│  │ Cluster   │   │ │  │ Cluster   │   │ │  │ Cluster   │   │
│  │ (3 nodes) │   │ │  │ (3 nodes) │   │ │  │ (3 nodes) │   │
│  └─────┬─────┘   │ │  └─────┬─────┘   │ │  └─────┬─────┘   │
│        │         │ │        │         │ │        │         │
│  ┌─────┴──────────────────────────────────────────┐         │
│  │        Game Server Cluster (per region)       │         │
│  │                                               │         │
│  │ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐          │         │
│  │ │Forest│ │Desert│ │Mount │ │Volc. │  ×3     │         │
│  │ │Shard │ │Shard │ │Shard │ │Shard │          │         │
│  │ └──────┘ └──────┘ └──────┘ └──────┘          │         │
│  └─────┬────────────────────────────────────────┘          │
│        │         │ │        │         │ │        │         │
│        ▼         │ │        ▼         │ │        ▼         │
│  PostgreSQL     │ │  PostgreSQL     │ │  PostgreSQL       │
│  Replica Set    │ │  Primary DB     │ │  Replica Set      │
│  (Read-only)    │ │  (Multi-zone)   │ │  (Read-only)      │
│                 │ │  HA enabled     │ │                   │
└─────────────────┘ │                  │ └───────────────────┘
                    │                  │
                    └──────────────────┘
                    │ │ │ │ │ │ │ │ │ │
                    └─┼─┴─┼─┴─┼─┴─┼─┘
                      │   │   │   │
                  ┌───┴───┴───┴───┴────┐
                  │   Global Redis     │
                  │  Cluster           │
                  │  (Leaderboards)    │
                  └────────────────────┘
```

### Regional Deployment

**Per Region (3 regions):**

```
SINGAPORE (Primary):
├─ 3-4 Game Servers (8C/16GB droplets)
│  ├─ Forest Shard (1-2 instances)
│  ├─ Desert Shard (1-2 instances)
│  ├─ Mountain Shard (1-2 instances)
│  └─ Volcanic Shard (1-2 instances)
├─ 3 API Servers (4C/8GB droplets)
├─ PostgreSQL Primary (DO Managed, HA)
└─ Redis Primary
   Cost: ~$800/month

FRANKFURT (Secondary):
├─ 2-3 Game Servers
├─ 2 API Servers (failover)
├─ PostgreSQL Replica
└─ Redis Replica
   Cost: ~$600/month

US-WEST (Tertiary):
├─ 2-3 Game Servers
├─ 2 API Servers (failover)
├─ PostgreSQL Replica
└─ Redis Replica
   Cost: ~$600/month

GLOBAL INFRASTRUCTURE:
├─ Load Balancers (per region): $10/mo × 3 = $30/mo
├─ CloudFlare CDN: $200-500/mo (Pro plan)
├─ Monitoring (Prometheus/Grafana): $0-100/mo
└─ VPN/Data Transfer: ~$100-200/mo

TOTAL: ~$2,300-2,500/month
```

### Scaling Decisions at Each Level

```
Player Count → Infrastructure Decision

0-100 players
  → Single droplet (all services)
  → Total: $96/mo

100-500 players
  → 2x game servers + separate API + managed DB
  → Total: $150-200/mo

500-2000 players
  → 5x game servers (by zone)
  → 2x API servers
  → Managed PostgreSQL HA
  → Total: $400-600/mo

2000-10000 players
  → 12+ game servers (by zone + shards)
  → 3-5 API servers
  → PostgreSQL HA + replicas
  → Redis cluster
  → Load balancers
  → Total: $1000-1500/mo

10000+ players (multi-region)
  → 20+ game servers per region
  → 3+ API servers per region
  → Full HA across regions
  → Global CDN
  → Total: $2000-5000+/mo
```

---

## Multi-Region Architecture

### Regional Strategy

```
PHASE TIMELINE:

ALPHA/BETA (Now):
└─ Singapore only
   └─ Game development focus
   └─ Low cost infrastructure

LAUNCH (Month 3-4):
├─ Singapore Primary (start high load testing)
└─ Ready for Frankfurt + US-West deployment

EXPANSION 1 (Month 4-5):
├─ Frankfurt Live (Europe players)
├─ Data replication begins
└─ Load distribution

EXPANSION 2 (Month 5-6):
├─ US-West Live (Americas players)
├─ Full 3-region operation
└─ Global leaderboards with latency compensation

MATURE (Month 6+):
├─ All 3 regions stable
├─ Auto-scaling per region
├─ Cross-region tournaments
└─ 10k+ concurrent players
```

### Data Replication Strategy

```
LEADERBOARDS (Redis Cluster):
├─ Replicate globally (critical for tournaments)
├─ Read-local, write-primary
└─ Latency: <100ms visible updates

CHARACTER DATA (PostgreSQL Replication):
├─ Primary in Singapore
├─ Read replicas in Frankfurt + US-West
├─ Writes go through Singapore (ensure consistency)
└─ Acceptable latency: 100-200ms for character saves

PLAYER STATE (Game Servers - Local):
├─ No replication needed (ephemeral)
├─ Each region maintains its own player positions
├─ Tournaments/PvP matchmake within region for low latency
└─ Cross-region tournaments handled via API
```

### Player Routing

```
GEOGRAPHIC ROUTING:

┌──────────────────────────────────┐
│ Player connects from IP address  │
└──────────┬───────────────────────┘
           │
           ▼
┌──────────────────────────────────┐
│ CloudFlare Geo-IP Lookup         │
│ ├─ Europe → Frankfurt            │
│ ├─ Asia-Pacific → Singapore      │
│ └─ Americas → US-West            │
└──────────┬───────────────────────┘
           │
           ▼
┌──────────────────────────────────┐
│ DNS returns regional API endpoint│
│ (Frankfurt.api.omgea.com)        │
└──────────┬───────────────────────┘
           │
           ▼
┌──────────────────────────────────┐
│ Connect to regional API cluster  │
│ → Load balancer → API server     │
└──────────┬───────────────────────┘
           │
           ▼
┌──────────────────────────────────┐
│ API returns game server IP       │
│ (game.sgp.omgea.com for example) │
└──────────┬───────────────────────┘
           │
           ▼
┌──────────────────────────────────┐
│ Connect directly to game server  │
│ (lowest latency path)            │
└──────────────────────────────────┘
```

### Cross-Region Communication

```
Game servers DON'T communicate directly.
Communication happens through API:

Game Server (Singapore)
    ↓ REST API Call
API Server (Singapore)
    ↓ Query shared database
PostgreSQL Primary (Singapore)
    ↓ Replication
PostgreSQL Replica (Frankfurt)
    ↓ Read query
API Server (Frankfurt)
    ↓ REST response
Game Server (Frankfurt)

Latency: <500ms for cross-region queries (acceptable)

For real-time features (arena, leaderboards):
├─ Players in different regions can queue together
├─ Matchmaking creates match in nearest region to both
├─ Arena standings replicated via Redis (global)
└─ Visible results within 1-2 seconds globally
```

---

## Load Balancing Strategy

### Option A: DNS-Based Routing (Simple, Free)

**Best for:** Alpha/Beta with single region

---

## Deployment Procedures

### Docker Deployment (Recommended)

### Monitoring with Prometheus
