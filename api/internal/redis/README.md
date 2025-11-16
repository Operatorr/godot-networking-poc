# Redis Integration

This package provides Redis integration for session management and leaderboard caching in the Omega Realm API.

## Overview

The Redis integration consists of three main components:

1. **Client** (`client.go`) - Redis connection management
2. **Sessions** (`session.go`) - User session caching with JWT tokens
3. **Leaderboards** (`leaderboard.go`) - Real-time leaderboard operations using sorted sets

## Features

### Session Management

- **Fast JWT Validation**: Cache session data to avoid database hits on every request
- **Active Users Tracking**: Track active users globally and per region
- **Session Lifecycle**: Create, retrieve, update, and invalidate sessions
- **TTL Support**: Automatic session expiration matching JWT token lifetime

### Leaderboard Caching

- **Real-time Updates**: Sub-millisecond leaderboard queries using Redis sorted sets
- **Multiple Leaderboards**: Separate tracking for PvP kills, monster kills, and deaths
- **Ranking Queries**: Get top N players, player rankings, and score ranges
- **Atomic Operations**: Use pipelines for concurrent stat updates

## Configuration

Configure Redis via environment variables in `.env`:

```bash
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0
REDIS_POOL_SIZE=10
REDIS_DIAL_TIMEOUT=10s
```

## Usage Examples

### Initialize Redis Client

```go
import (
    redisClient "github.com/omega-realm/api/internal/redis"
)

func main() {
    config := redisClient.LoadConfigFromEnv()
    redis, err := redisClient.NewClient(config)
    if err != nil {
        log.Fatal(err)
    }
    defer redis.Close()
}
```

### Session Operations

```go
import (
    "context"
    "time"
)

ctx := context.Background()

// Create a session
session := &redisClient.SessionData{
    UserID:    123,
    Username:  "player1",
    Email:     "player1@example.com",
    Region:    "Asia",
    CreatedAt: time.Now(),
    ExpiresAt: time.Now().Add(24 * time.Hour),
}

// Store session with 24-hour TTL
err := redis.SetSession(ctx, "jwt-token-here", session, 24*time.Hour)

// Retrieve session
session, err := redis.GetSession(ctx, "jwt-token-here")

// Update session with game server info
err = redis.UpdateSessionGameServer(ctx, "jwt-token-here", 456, "Asia")

// Delete session (logout)
err = redis.DeleteSession(ctx, "jwt-token-here")

// Get active users count
count, err := redis.GetActiveUsersCount(ctx)

// Get active users in a region
asiaCount, err := redis.GetActiveUsersByRegion(ctx, "Asia")
```

### Leaderboard Operations

```go
ctx := context.Background()

// Record a PvP kill (increments both killer and victim stats)
err := redis.RecordKill(ctx, killerID, victimID, true)

// Update individual stats
err = redis.UpdatePvPKills(ctx, characterID, 1)
err = redis.UpdateMonsterKills(ctx, characterID, 5)
err = redis.UpdateDeaths(ctx, characterID, 1)

// Get top 10 PvP players
topPlayers, err := redis.GetTopPvPPlayers(ctx, 10)
for i, player := range topPlayers {
    characterID := player.Member.(string)
    score := player.Score
    fmt.Printf("#%d: Character %s with %d kills\n", i+1, characterID, int(score))
}

// Get player's rank and score
entry, err := redis.GetPlayerRankings(ctx, characterID)
fmt.Printf("Character %d is rank #%d with score %.0f\n",
    entry.CharacterID, entry.Rank, entry.Score)

// Initialize cache from database
err = redis.SetPlayerStats(ctx, characterID, pvpKills, monsterKills, deaths)

// Get leaderboard size
size, err := redis.GetLeaderboardSize(ctx)
```

## Data Structures

### Sessions

Sessions are stored as JSON strings with the key pattern: `session:{jwt-token}`

Active users are tracked in sets:
- `active_users` - Global set of active user IDs
- `active_users:{region}` - Region-specific sets (e.g., `active_users:Asia`)

### Leaderboards

Leaderboards use Redis Sorted Sets with the following keys:
- `leaderboard:pvp` - PvP kills (score = kill count, member = character ID)
- `leaderboard:monster` - Monster kills
- `leaderboard:deaths` - Death count

## Performance Considerations

1. **Connection Pooling**: Default pool size is 10, configurable via `REDIS_POOL_SIZE`
2. **Pipelining**: Batch operations use pipelines to reduce network round trips
3. **TTL Management**: Sessions automatically expire to prevent memory bloat
4. **Atomic Updates**: Use `ZIncrBy` for thread-safe score increments

## Integration with Existing Handlers

To integrate Redis with your handlers, pass the Redis client alongside the database:

```go
// In main.go
authHandler := handlers.NewAuthHandler(db, redis)
leaderboardHandler := handlers.NewLeaderboardHandler(db, redis)

// In handler
func (h *AuthHandler) Login(w http.ResponseWriter, r *http.Request) {
    // ... authenticate user ...

    // Create session in Redis
    session := &redisClient.SessionData{...}
    h.redis.SetSession(ctx, token, session, 24*time.Hour)
}
```

## Error Handling

All Redis operations return errors that should be handled appropriately:

```go
session, err := redis.GetSession(ctx, token)
if err != nil {
    // Session not found or Redis error
    // Fall back to database or return unauthorized
}
```

## Best Practices

1. **Use Context**: Always pass context for timeout and cancellation support
2. **Handle Redis Failures Gracefully**: Design fallbacks to database if Redis is unavailable
3. **Sync with Database**: Periodically sync leaderboard data with PostgreSQL
4. **Monitor Performance**: Track Redis pool stats and connection health
5. **Set Appropriate TTLs**: Match session TTLs with JWT expiration times

## Running Redis Locally

For local development, run Redis with Docker:

```bash
docker run -d -p 6379:6379 --name redis redis:7-alpine
```

Or install Redis directly:

```bash
# macOS
brew install redis
brew services start redis

# Ubuntu/Debian
sudo apt-get install redis-server
sudo systemctl start redis
```

## Testing

The API server will fail to start if Redis is not available. Ensure Redis is running before starting the server:

```bash
# Test Redis connection
redis-cli ping
# Expected output: PONG

# Start API server
go run ./cmd/server/main.go
```

## Future Enhancements

- [ ] Add session blacklist for revoked tokens
- [ ] Implement rate limiting using Redis
- [ ] Add caching for frequently accessed game data
- [ ] Implement pub/sub for real-time game events
- [ ] Add Redis Cluster support for horizontal scaling
