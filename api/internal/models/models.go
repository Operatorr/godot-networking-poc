package models

import "time"

// User represents a user account
type User struct {
	ID           int       `json:"id"`
	Username     string    `json:"username"`
	Email        string    `json:"email"`
	PasswordHash string    `json:"-"`
	Region       string    `json:"region"`
	CreatedAt    time.Time `json:"created_at"`
}

// Character represents a player character
type Character struct {
	ID        int       `json:"id"`
	UserID    int       `json:"user_id"`
	Name      string    `json:"name"`
	CreatedAt time.Time `json:"created_at"`
}

// Leaderboard represents leaderboard stats
type Leaderboard struct {
	ID            int       `json:"id"`
	CharacterID   int       `json:"character_id"`
	PvPKills      int       `json:"pvp_kills"`
	MonsterKills  int       `json:"monster_kills"`
	Deaths        int       `json:"deaths"`
	UpdatedAt     time.Time `json:"updated_at"`
}

// Session represents a game session
type Session struct {
	ID           int        `json:"id"`
	CharacterID  int        `json:"character_id"`
	ServerRegion string     `json:"server_region"`
	StartedAt    time.Time  `json:"started_at"`
	EndedAt      *time.Time `json:"ended_at"`
}
