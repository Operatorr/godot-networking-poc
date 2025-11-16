package redis

import (
	"context"
	"fmt"

	"github.com/redis/go-redis/v9"
)

// LeaderboardEntry represents a player's position and stats on the leaderboard
type LeaderboardEntry struct {
	CharacterID   int     `json:"character_id"`
	CharacterName string  `json:"character_name"`
	Score         float64 `json:"score"`
	Rank          int64   `json:"rank"`
}

// LeaderboardStats represents detailed stats for a character
type LeaderboardStats struct {
	CharacterID  int `json:"character_id"`
	PvPKills     int `json:"pvp_kills"`
	MonsterKills int `json:"monster_kills"`
	Deaths       int `json:"deaths"`
}

const (
	// Leaderboard keys
	leaderboardPvPKey     = "leaderboard:pvp"
	leaderboardMonsterKey = "leaderboard:monster"
	leaderboardDeathsKey  = "leaderboard:deaths"
)

// UpdatePvPKills increments the PvP kills for a character
func (c *Client) UpdatePvPKills(ctx context.Context, characterID int, kills int) error {
	return c.ZIncrBy(ctx, leaderboardPvPKey, float64(kills), fmt.Sprintf("%d", characterID)).Err()
}

// UpdateMonsterKills increments the monster kills for a character
func (c *Client) UpdateMonsterKills(ctx context.Context, characterID int, kills int) error {
	return c.ZIncrBy(ctx, leaderboardMonsterKey, float64(kills), fmt.Sprintf("%d", characterID)).Err()
}

// UpdateDeaths increments the deaths for a character
func (c *Client) UpdateDeaths(ctx context.Context, characterID int, deaths int) error {
	return c.ZIncrBy(ctx, leaderboardDeathsKey, float64(deaths), fmt.Sprintf("%d", characterID)).Err()
}

// GetTopPvPPlayers returns the top N players by PvP kills
func (c *Client) GetTopPvPPlayers(ctx context.Context, limit int64) ([]redis.Z, error) {
	// Get top players (highest scores first)
	players, err := c.ZRevRangeWithScores(ctx, leaderboardPvPKey, 0, limit-1).Result()
	if err != nil {
		return nil, fmt.Errorf("failed to get top PvP players: %w", err)
	}
	return players, nil
}

// GetTopMonsterKillers returns the top N players by monster kills
func (c *Client) GetTopMonsterKillers(ctx context.Context, limit int64) ([]redis.Z, error) {
	players, err := c.ZRevRangeWithScores(ctx, leaderboardMonsterKey, 0, limit-1).Result()
	if err != nil {
		return nil, fmt.Errorf("failed to get top monster killers: %w", err)
	}
	return players, nil
}

// GetPlayerPvPScore returns the PvP score for a specific character
func (c *Client) GetPlayerPvPScore(ctx context.Context, characterID int) (float64, error) {
	score, err := c.ZScore(ctx, leaderboardPvPKey, fmt.Sprintf("%d", characterID)).Result()
	if err != nil {
		return 0, fmt.Errorf("failed to get player PvP score: %w", err)
	}
	return score, nil
}

// GetPlayerMonsterScore returns the monster kill score for a specific character
func (c *Client) GetPlayerMonsterScore(ctx context.Context, characterID int) (float64, error) {
	score, err := c.ZScore(ctx, leaderboardMonsterKey, fmt.Sprintf("%d", characterID)).Result()
	if err != nil {
		return 0, fmt.Errorf("failed to get player monster score: %w", err)
	}
	return score, nil
}

// GetPlayerPvPRank returns the rank of a player in the PvP leaderboard (1-based)
func (c *Client) GetPlayerPvPRank(ctx context.Context, characterID int) (int64, error) {
	// ZRevRank returns 0-based rank, so add 1 for 1-based ranking
	rank, err := c.ZRevRank(ctx, leaderboardPvPKey, fmt.Sprintf("%d", characterID)).Result()
	if err != nil {
		return 0, fmt.Errorf("failed to get player PvP rank: %w", err)
	}
	return rank + 1, nil
}

// SetPlayerStats sets all stats for a character (used for cache initialization from DB)
func (c *Client) SetPlayerStats(ctx context.Context, characterID int, pvpKills, monsterKills, deaths int) error {
	// Use pipeline to set all stats atomically
	pipe := c.Pipeline()

	pipe.ZAdd(ctx, leaderboardPvPKey, redis.Z{
		Score:  float64(pvpKills),
		Member: fmt.Sprintf("%d", characterID),
	})

	pipe.ZAdd(ctx, leaderboardMonsterKey, redis.Z{
		Score:  float64(monsterKills),
		Member: fmt.Sprintf("%d", characterID),
	})

	pipe.ZAdd(ctx, leaderboardDeathsKey, redis.Z{
		Score:  float64(deaths),
		Member: fmt.Sprintf("%d", characterID),
	})

	_, err := pipe.Exec(ctx)
	if err != nil {
		return fmt.Errorf("failed to set player stats: %w", err)
	}

	return nil
}

// RemovePlayer removes a character from all leaderboards
func (c *Client) RemovePlayer(ctx context.Context, characterID int) error {
	pipe := c.Pipeline()

	memberID := fmt.Sprintf("%d", characterID)
	pipe.ZRem(ctx, leaderboardPvPKey, memberID)
	pipe.ZRem(ctx, leaderboardMonsterKey, memberID)
	pipe.ZRem(ctx, leaderboardDeathsKey, memberID)

	_, err := pipe.Exec(ctx)
	if err != nil {
		return fmt.Errorf("failed to remove player from leaderboards: %w", err)
	}

	return nil
}

// GetLeaderboardSize returns the total number of players in the PvP leaderboard
func (c *Client) GetLeaderboardSize(ctx context.Context) (int64, error) {
	count, err := c.ZCard(ctx, leaderboardPvPKey).Result()
	if err != nil {
		return 0, fmt.Errorf("failed to get leaderboard size: %w", err)
	}
	return count, nil
}

// GetPlayersByScoreRange returns players with scores in a specific range
func (c *Client) GetPlayersByScoreRange(ctx context.Context, min, max float64) ([]redis.Z, error) {
	players, err := c.ZRangeByScoreWithScores(ctx, leaderboardPvPKey, &redis.ZRangeBy{
		Min: fmt.Sprintf("%f", min),
		Max: fmt.Sprintf("%f", max),
	}).Result()
	if err != nil {
		return nil, fmt.Errorf("failed to get players by score range: %w", err)
	}
	return players, nil
}

// ClearAllLeaderboards removes all leaderboard data (use with caution)
func (c *Client) ClearAllLeaderboards(ctx context.Context) error {
	pipe := c.Pipeline()

	pipe.Del(ctx, leaderboardPvPKey)
	pipe.Del(ctx, leaderboardMonsterKey)
	pipe.Del(ctx, leaderboardDeathsKey)

	_, err := pipe.Exec(ctx)
	if err != nil {
		return fmt.Errorf("failed to clear leaderboards: %w", err)
	}

	return nil
}

// GetPlayerRankings returns comprehensive ranking information for a character
func (c *Client) GetPlayerRankings(ctx context.Context, characterID int) (*LeaderboardEntry, error) {
	memberID := fmt.Sprintf("%d", characterID)

	// Get score
	score, err := c.ZScore(ctx, leaderboardPvPKey, memberID).Result()
	if err != nil {
		return nil, fmt.Errorf("character not found in leaderboard: %w", err)
	}

	// Get rank (0-based, so add 1)
	rank, err := c.ZRevRank(ctx, leaderboardPvPKey, memberID).Result()
	if err != nil {
		return nil, fmt.Errorf("failed to get rank: %w", err)
	}

	return &LeaderboardEntry{
		CharacterID: characterID,
		Score:       score,
		Rank:        rank + 1,
	}, nil
}

// RecordKill is a convenience method that updates both killer and victim stats
func (c *Client) RecordKill(ctx context.Context, killerID, victimID int, isPvP bool) error {
	pipe := c.Pipeline()

	if isPvP {
		// Increment killer's PvP kills
		pipe.ZIncrBy(ctx, leaderboardPvPKey, 1, fmt.Sprintf("%d", killerID))
		// Increment victim's deaths
		pipe.ZIncrBy(ctx, leaderboardDeathsKey, 1, fmt.Sprintf("%d", victimID))
	} else {
		// Monster kill
		pipe.ZIncrBy(ctx, leaderboardMonsterKey, 1, fmt.Sprintf("%d", killerID))
	}

	_, err := pipe.Exec(ctx)
	if err != nil {
		return fmt.Errorf("failed to record kill: %w", err)
	}

	return nil
}
