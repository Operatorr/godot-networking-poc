package redis

import (
	"context"
	"encoding/json"
	"fmt"
	"time"
)

const regionStatusKeyPrefix = "region_status:"

// RegionRuntimeStatus is the live status published by a game server.
type RegionRuntimeStatus struct {
	RegionID      string    `json:"region_id"`
	ActivePlayers int64     `json:"active_players"`
	MaxPlayers    int       `json:"max_players"`
	ConnectURL    string    `json:"connect_url,omitempty"`
	Status        string    `json:"status"`
	UpdatedAt     time.Time `json:"updated_at"`
}

// SetRegionRuntimeStatus stores a short-lived live status for a game region.
func (c *Client) SetRegionRuntimeStatus(ctx context.Context, status *RegionRuntimeStatus, ttl time.Duration) error {
	if status == nil {
		return fmt.Errorf("region runtime status is nil")
	}

	status.UpdatedAt = time.Now().UTC()
	statusJSON, err := json.Marshal(status)
	if err != nil {
		return fmt.Errorf("failed to marshal region runtime status: %w", err)
	}

	key := regionStatusKeyPrefix + status.RegionID
	if err := c.Set(ctx, key, statusJSON, ttl).Err(); err != nil {
		return fmt.Errorf("failed to set region runtime status: %w", err)
	}

	return nil
}

// GetRegionRuntimeStatus returns the current live status for a game region.
func (c *Client) GetRegionRuntimeStatus(ctx context.Context, regionID string) (*RegionRuntimeStatus, error) {
	statusJSON, err := c.Get(ctx, regionStatusKeyPrefix+regionID).Result()
	if err != nil {
		return nil, fmt.Errorf("region runtime status not found: %w", err)
	}

	var status RegionRuntimeStatus
	if err := json.Unmarshal([]byte(statusJSON), &status); err != nil {
		return nil, fmt.Errorf("failed to unmarshal region runtime status: %w", err)
	}

	return &status, nil
}
