package models

import (
	"os"
	"strings"
)

// Region represents a game server region
type Region struct {
	ID              string `json:"id"`
	DisplayName     string `json:"display_name"`
	ConnectURL      string `json:"connect_url"`
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
	RegionLocal  = "local"
	RegionAsia   = "asia"
	RegionEurope = "europe"
	RegionUSWest = "us-west"
)

// ValidRegions is a map of valid region IDs
var ValidRegions = map[string]bool{
	RegionLocal:  true,
	RegionAsia:   true,
	RegionEurope: true,
	RegionUSWest: true,
}

// IsValidRegion checks if a region ID is valid
func IsValidRegion(regionID string) bool {
	return ValidRegions[regionID]
}

// regionConnectURL resolves a region's advertised connect address. Operators set
// REGION_<ID>_URL (e.g. REGION_EUROPE_URL=fra.omega.example:8081) to point a region at its
// game-server droplet. The value is a bare host:port for the ENet/UDP game server
// (ADR 0003 — no scheme, no TLS); the client's _split_host_port tolerates a leftover scheme
// if one slips in. This is only the *fallback*: a live game server's heartbeat advertise_url
// overrides it at runtime (see handlers/region.go applyRuntimeStatuses), so it is what the API
// reports when a server is up but has not advertised its own address. Empty means "no static
// fallback — rely on the heartbeat", which is the norm in production.
func regionConnectURL(envKey, fallback string) string {
	if v := strings.TrimSpace(os.Getenv(envKey)); v != "" {
		return v
	}
	return fallback
}

// GetRegionDetails returns details for a region. Connect URLs come from REGION_<ID>_URL env
// vars (with a runtime heartbeat override); capacity/latency are static metadata.
func GetRegionDetails(regionID string) *Region {
	regions := map[string]*Region{
		RegionLocal: {
			ID:              RegionLocal,
			DisplayName:     "Local",
			ConnectURL:      regionConnectURL("REGION_LOCAL_URL", "localhost:8081"),
			Status:          RegionStatusOnline,
			MaxPlayers:      100,
			LatencyEstimate: "< 10ms",
		},
		RegionAsia: {
			ID:              RegionAsia,
			DisplayName:     "Asia",
			ConnectURL:      regionConnectURL("REGION_ASIA_URL", ""),
			Status:          RegionStatusOnline,
			MaxPlayers:      200,
			LatencyEstimate: "< 80ms",
		},
		RegionEurope: {
			ID:              RegionEurope,
			DisplayName:     "Europe",
			ConnectURL:      regionConnectURL("REGION_EUROPE_URL", ""),
			Status:          RegionStatusOnline,
			MaxPlayers:      200,
			LatencyEstimate: "< 80ms",
		},
		RegionUSWest: {
			ID:              RegionUSWest,
			DisplayName:     "US West",
			ConnectURL:      regionConnectURL("REGION_US_WEST_URL", ""),
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
		GetRegionDetails(RegionLocal),
		GetRegionDetails(RegionAsia),
		GetRegionDetails(RegionEurope),
		GetRegionDetails(RegionUSWest),
	}
}
