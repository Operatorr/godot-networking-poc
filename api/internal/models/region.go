package models

// Region represents a game server region
type Region struct {
	ID              string `json:"id"`
	DisplayName     string `json:"display_name"`
	WebSocketURL    string `json:"websocket_url"`
	Status          string `json:"status"`
	ActivePlayers   int64  `json:"active_players"`
	MaxPlayers      int    `json:"max_players"`
	LatencyEstimate string `json:"latency_estimate"`
}

// RegionStatus constants
const (
	RegionStatusOnline      = "online"
	RegionStatusOffline     = "offline"
	RegionStatusMaintenance = "maintenance"
)

// Region ID constants
const (
	RegionAsia   = "asia"
	RegionEurope = "europe"
	RegionUSWest = "us-west"
)

// ValidRegions is a map of valid region IDs
var ValidRegions = map[string]bool{
	RegionAsia:   true,
	RegionEurope: true,
	RegionUSWest: true,
}

// IsValidRegion checks if a region ID is valid
func IsValidRegion(regionID string) bool {
	return ValidRegions[regionID]
}

// GetRegionDetails returns static details for a region
func GetRegionDetails(regionID string) *Region {
	// In production, WebSocket URLs would come from environment variables
	// For now, we'll use placeholder URLs
	regions := map[string]*Region{
		RegionAsia: {
			ID:              RegionAsia,
			DisplayName:     "Asia",
			WebSocketURL:    "ws://asia.omegagame.io:9001",
			Status:          RegionStatusOnline,
			MaxPlayers:      200,
			LatencyEstimate: "< 50ms",
		},
		RegionEurope: {
			ID:              RegionEurope,
			DisplayName:     "Europe",
			WebSocketURL:    "ws://europe.omegagame.io:9001",
			Status:          RegionStatusOnline,
			MaxPlayers:      200,
			LatencyEstimate: "< 80ms",
		},
		RegionUSWest: {
			ID:              RegionUSWest,
			DisplayName:     "US West",
			WebSocketURL:    "ws://us-west.omegagame.io:9001",
			Status:          RegionStatusOnline,
			MaxPlayers:      200,
			LatencyEstimate: "< 100ms",
		},
	}

	return regions[regionID]
}

// GetAllRegions returns all available regions
func GetAllRegions() []*Region {
	return []*Region{
		GetRegionDetails(RegionAsia),
		GetRegionDetails(RegionEurope),
		GetRegionDetails(RegionUSWest),
	}
}
