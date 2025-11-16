package redis

import (
	"context"
	"encoding/json"
	"fmt"
	"time"
)

// SessionData represents a user session stored in Redis
type SessionData struct {
	UserID       int       `json:"user_id"`
	Username     string    `json:"username"`
	Email        string    `json:"email"`
	Region       string    `json:"region"`
	CharacterID  int       `json:"character_id,omitempty"`
	ServerRegion string    `json:"server_region,omitempty"`
	CreatedAt    time.Time `json:"created_at"`
	ExpiresAt    time.Time `json:"expires_at"`
}

// SetSession stores a user session in Redis with TTL
func (c *Client) SetSession(ctx context.Context, token string, session *SessionData, ttl time.Duration) error {
	sessionKey := fmt.Sprintf("session:%s", token)

	// Serialize session data to JSON
	sessionJSON, err := json.Marshal(session)
	if err != nil {
		return fmt.Errorf("failed to marshal session data: %w", err)
	}

	// Store session with expiration
	if err := c.Set(ctx, sessionKey, sessionJSON, ttl).Err(); err != nil {
		return fmt.Errorf("failed to set session: %w", err)
	}

	// Add user to active users set
	activeUsersKey := "active_users"
	if err := c.SAdd(ctx, activeUsersKey, session.UserID).Err(); err != nil {
		return fmt.Errorf("failed to add to active users: %w", err)
	}

	// Add user to region-specific active users set
	regionActiveUsersKey := fmt.Sprintf("active_users:%s", session.Region)
	if err := c.SAdd(ctx, regionActiveUsersKey, session.UserID).Err(); err != nil {
		return fmt.Errorf("failed to add to region active users: %w", err)
	}

	return nil
}

// GetSession retrieves a user session from Redis
func (c *Client) GetSession(ctx context.Context, token string) (*SessionData, error) {
	sessionKey := fmt.Sprintf("session:%s", token)

	// Get session data
	sessionJSON, err := c.Get(ctx, sessionKey).Result()
	if err != nil {
		return nil, fmt.Errorf("session not found: %w", err)
	}

	// Deserialize session data
	var session SessionData
	if err := json.Unmarshal([]byte(sessionJSON), &session); err != nil {
		return nil, fmt.Errorf("failed to unmarshal session data: %w", err)
	}

	return &session, nil
}

// DeleteSession removes a user session from Redis (for logout)
func (c *Client) DeleteSession(ctx context.Context, token string) error {
	sessionKey := fmt.Sprintf("session:%s", token)

	// Get session data first to update active users
	session, err := c.GetSession(ctx, token)
	if err == nil {
		// Remove from active users sets
		c.SRem(ctx, "active_users", session.UserID)
		c.SRem(ctx, fmt.Sprintf("active_users:%s", session.Region), session.UserID)
	}

	// Delete the session key
	if err := c.Del(ctx, sessionKey).Err(); err != nil {
		return fmt.Errorf("failed to delete session: %w", err)
	}

	return nil
}

// InvalidateUserSessions removes all sessions for a specific user
func (c *Client) InvalidateUserSessions(ctx context.Context, userID int) error {
	// Scan for all session keys
	pattern := "session:*"
	iter := c.Scan(ctx, 0, pattern, 100).Iterator()

	for iter.Next(ctx) {
		sessionKey := iter.Val()

		// Get session data to check user ID
		sessionJSON, err := c.Get(ctx, sessionKey).Result()
		if err != nil {
			continue
		}

		var session SessionData
		if err := json.Unmarshal([]byte(sessionJSON), &session); err != nil {
			continue
		}

		// Delete if it matches the user ID
		if session.UserID == userID {
			c.Del(ctx, sessionKey)
		}
	}

	if err := iter.Err(); err != nil {
		return fmt.Errorf("failed to scan sessions: %w", err)
	}

	// Remove from active users sets
	c.SRem(ctx, "active_users", userID)
	// Note: We don't know the region, so we'll leave region-specific cleanup to TTL

	return nil
}

// GetActiveUsersCount returns the total number of active users
func (c *Client) GetActiveUsersCount(ctx context.Context) (int64, error) {
	count, err := c.SCard(ctx, "active_users").Result()
	if err != nil {
		return 0, fmt.Errorf("failed to get active users count: %w", err)
	}
	return count, nil
}

// GetActiveUsersByRegion returns the number of active users in a specific region
func (c *Client) GetActiveUsersByRegion(ctx context.Context, region string) (int64, error) {
	regionKey := fmt.Sprintf("active_users:%s", region)
	count, err := c.SCard(ctx, regionKey).Result()
	if err != nil {
		return 0, fmt.Errorf("failed to get active users for region %s: %w", region, err)
	}
	return count, nil
}

// RefreshSessionTTL extends the TTL of an existing session
func (c *Client) RefreshSessionTTL(ctx context.Context, token string, ttl time.Duration) error {
	sessionKey := fmt.Sprintf("session:%s", token)

	// Check if session exists
	exists, err := c.Exists(ctx, sessionKey).Result()
	if err != nil {
		return fmt.Errorf("failed to check session existence: %w", err)
	}

	if exists == 0 {
		return fmt.Errorf("session not found")
	}

	// Update TTL
	if err := c.Expire(ctx, sessionKey, ttl).Err(); err != nil {
		return fmt.Errorf("failed to refresh session TTL: %w", err)
	}

	return nil
}

// UpdateSessionGameServer updates the game server information for a session
func (c *Client) UpdateSessionGameServer(ctx context.Context, token string, characterID int, serverRegion string) error {
	sessionKey := fmt.Sprintf("session:%s", token)

	// Get existing session
	session, err := c.GetSession(ctx, token)
	if err != nil {
		return err
	}

	// Update game server information
	session.CharacterID = characterID
	session.ServerRegion = serverRegion

	// Serialize and save
	sessionJSON, err := json.Marshal(session)
	if err != nil {
		return fmt.Errorf("failed to marshal session data: %w", err)
	}

	// Get current TTL to preserve it
	ttl, err := c.TTL(ctx, sessionKey).Result()
	if err != nil {
		return fmt.Errorf("failed to get session TTL: %w", err)
	}

	// Update session while preserving TTL
	if err := c.Set(ctx, sessionKey, sessionJSON, ttl).Err(); err != nil {
		return fmt.Errorf("failed to update session: %w", err)
	}

	return nil
}
