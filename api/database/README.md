# Database Documentation

## Overview

The Omega Realm backend uses PostgreSQL as its primary database for storing user accounts, characters, leaderboards, and session data.

## Schema

The database consists of 4 main tables:

### 1. Users Table
- **Purpose**: Store player account information and authentication data
- **Key Features**:
  - Unique username and email
  - Bcrypt-hashed passwords
  - Region preference (Asia, Europe, US-West)
  - Account creation timestamp

### 2. Characters Table
- **Purpose**: Store player characters (one per user)
- **Key Features**:
  - **UNIQUE constraint on user_id** ensures single character per player
  - Unique character names across all players
  - Character creation timestamp

### 3. Leaderboards Table
- **Purpose**: Track player statistics for rankings
- **Key Features**:
  - PvP kills (player vs player)
  - Monster kills
  - Death count
  - Auto-updated timestamp on stat changes
  - **Automatically created** when a character is created (via trigger)

### 4. Sessions Table
- **Purpose**: Track active and historical game sessions
- **Key Features**:
  - Session start time
  - Session end time (NULL for active sessions)
  - Server region
  - Multiple sessions per character allowed

## Indexes

Optimized indexes for common queries:

- **Users**: username, email, region, created_at
- **Characters**: user_id, name, created_at
- **Leaderboards**: character_id, pvp_kills (DESC), monster_kills (DESC), updated_at
- **Sessions**: character_id, server_region, started_at, active sessions

## Triggers

### 1. Auto-update Leaderboard Timestamp
- **Trigger**: `trg_update_leaderboard_timestamp`
- **Action**: Automatically updates `updated_at` field when leaderboard stats change

### 2. Auto-create Leaderboard Entry
- **Trigger**: `trg_create_leaderboard_entry`
- **Action**: Creates a leaderboard entry with 0 stats when a new character is created

## Views

### 1. v_pvp_leaderboard
- Top 100 PvP players with K/D ratios
- Sorted by PvP kills (descending)
- Includes character name, username, region, stats

### 2. v_active_sessions
- Currently active game sessions
- Shows session duration in minutes
- Includes character info and server region

## Setup

### Option 1: Using the Go Application
The Go API automatically initializes the schema when it starts:

```bash
cd api
go run cmd/server/main.go
```

### Option 2: Manual Setup with psql
```bash
# Create database
createdb omega_db

# Apply schema
psql -U omega -d omega_db -f database/schema.sql
```

### Option 3: Using Docker
```bash
# Start PostgreSQL container
docker run --name omega-postgres \
  -e POSTGRES_DB=omega_db \
  -e POSTGRES_USER=omega \
  -e POSTGRES_PASSWORD=omega_password \
  -p 5432:5432 \
  -d postgres:15

# Apply schema
docker exec -i omega-postgres psql -U omega -d omega_db < database/schema.sql
```

## Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
DB_HOST=localhost          # Database host
DB_PORT=5432              # Database port
DB_USER=omega             # Database user
DB_PASSWORD=your_password # Database password
DB_NAME=omega_db          # Database name
DB_SSLMODE=disable        # SSL mode (disable, require, verify-full)

# Connection Pool Settings
DB_MAX_OPEN_CONNS=25      # Max simultaneous connections
DB_MAX_IDLE_CONNS=5       # Max idle connections in pool
DB_CONN_MAX_LIFETIME=5m   # Connection lifetime
DB_CONN_MAX_IDLE_TIME=10m # Idle connection timeout
```

## Connection Pool Configuration

The database uses a connection pool for optimal performance:

- **Max Open Connections**: 25 (configurable)
- **Max Idle Connections**: 5 (configurable)
- **Connection Max Lifetime**: 5 minutes (configurable)
- **Connection Max Idle Time**: 10 minutes (configurable)

These settings are tuned for a game server handling 100+ concurrent players.

## Common Queries

### Get Top 10 PvP Players
```sql
SELECT * FROM v_pvp_leaderboard LIMIT 10;
```

### Get User's Character and Stats
```sql
SELECT c.*, l.pvp_kills, l.monster_kills, l.deaths
FROM characters c
LEFT JOIN leaderboards l ON c.id = l.character_id
WHERE c.user_id = $1;
```

### Update Player Kills
```sql
UPDATE leaderboards
SET pvp_kills = pvp_kills + 1
WHERE character_id = $1;
```

### Get Active Sessions by Region
```sql
SELECT * FROM v_active_sessions WHERE server_region = 'Asia';
```

### End a Session
```sql
UPDATE sessions
SET ended_at = CURRENT_TIMESTAMP
WHERE id = $1 AND ended_at IS NULL;
```

## Performance Considerations

1. **Indexes**: All frequently queried columns are indexed
2. **Connection Pooling**: Reuses database connections for efficiency
3. **Triggers**: Automate common operations to reduce application logic
4. **Views**: Pre-computed queries for complex leaderboard calculations
5. **Constraints**: Database-level validation ensures data integrity

## Security

- Passwords are **never** stored in plaintext (bcrypt hashing)
- `PasswordHash` field is excluded from JSON responses (json:"-" tag)
- Input validation at database level (CHECK constraints)
- Prepared statements prevent SQL injection
- CASCADE deletion ensures orphaned records are cleaned up

## Migrations

Currently using schema initialization on startup. For production, consider:

- [golang-migrate](https://github.com/golang-migrate/migrate)
- [goose](https://github.com/pressly/goose)
- [atlas](https://atlasgo.io/)

## Monitoring

### Check Database Size
```sql
SELECT pg_size_pretty(pg_database_size('omega_db')) AS size;
```

### Check Table Sizes
```sql
SELECT
    tablename,
    pg_size_pretty(pg_total_relation_size('public.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size('public.'||tablename) DESC;
```

### Check Active Connections
```sql
SELECT count(*) FROM pg_stat_activity WHERE datname = 'omega_db';
```

## Backup and Restore

### Backup
```bash
pg_dump -U omega -d omega_db > backup.sql
```

### Restore
```bash
psql -U omega -d omega_db < backup.sql
```

## Next Steps

- [ ] Implement proper migration system
- [ ] Add Redis caching for leaderboards (TASK-008)
- [ ] Set up database monitoring and alerting
- [ ] Implement automatic backups
- [ ] Add database replication for high availability
