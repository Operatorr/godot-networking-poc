package handlers

import (
	"context"
	"encoding/json"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/omega-realm/api/internal/middleware"
	"github.com/omega-realm/api/internal/models"
	redisClient "github.com/omega-realm/api/internal/redis"
)

type RegionHandler struct {
	redis *redisClient.Client
}

const regionRuntimeStatusTTL = 5 * time.Second

func NewRegionHandler(redis *redisClient.Client) *RegionHandler {
	return &RegionHandler{redis: redis}
}

// SelectRegionRequest represents the request body for region selection
type SelectRegionRequest struct {
	RegionID string `json:"region_id"`
}

// SelectRegionResponse represents the response after selecting a region
type SelectRegionResponse struct {
	Message      string         `json:"message"`
	Region       *models.Region `json:"region"`
	WebSocketURL string         `json:"websocket_url"`
}

// RegionHeartbeatRequest is published by game servers so the API can expose
// live region capacity without relying on login-session counts.
type RegionHeartbeatRequest struct {
	RegionID      string `json:"region_id"`
	Region        string `json:"region"`
	ActivePlayers int64  `json:"active_players"`
	MaxPlayers    int    `json:"max_players"`
	WebSocketURL  string `json:"websocket_url"`
	Status        string `json:"status"`
}

// GetRegions returns all available regions with their current player counts
func (h *RegionHandler) GetRegions(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	w.Header().Set("Content-Type", "application/json")

	regions := models.GetAllRegions()
	heartbeatApplied := h.applyRuntimeStatuses(r.Context(), regions)
	regions = onlineRegions(regions, heartbeatApplied)

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]any{
		"regions": regions,
	})
}

// UpdateRegionHeartbeat receives live status from a game server.
func (h *RegionHandler) UpdateRegionHeartbeat(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	w.Header().Set("Content-Type", "application/json")

	// Fail closed, mirroring internal.go's requireServerToken: an unset
	// REGION_HEARTBEAT_TOKEN rejects the request (503) unless the operator has
	// explicitly opted into the insecure dev path via ALLOW_INSECURE_INTERNAL=true.
	expectedToken := os.Getenv("REGION_HEARTBEAT_TOKEN")
	if expectedToken == "" {
		if os.Getenv("ALLOW_INSECURE_INTERNAL") != "true" {
			w.WriteHeader(http.StatusServiceUnavailable)
			json.NewEncoder(w).Encode(ErrorResponse{Error: "Region heartbeat unconfigured (set REGION_HEARTBEAT_TOKEN)"})
			return
		}
	} else if !serverTokenValid(r.Header.Get("X-Region-Heartbeat-Token"), expectedToken) {
		w.WriteHeader(http.StatusUnauthorized)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Unauthorized"})
		return
	}

	var req RegionHeartbeatRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid request body"})
		return
	}

	regionID := strings.ToLower(strings.TrimSpace(req.RegionID))
	if regionID == "" {
		regionID = strings.ToLower(strings.TrimSpace(req.Region))
	}
	if !models.IsValidRegion(regionID) {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid region"})
		return
	}

	region := models.GetRegionDetails(regionID)
	if region == nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid region"})
		return
	}

	maxPlayers := req.MaxPlayers
	if maxPlayers <= 0 {
		maxPlayers = region.MaxPlayers
	}
	activePlayers := req.ActivePlayers
	if activePlayers < 0 {
		activePlayers = 0
	}
	if activePlayers > int64(maxPlayers) {
		activePlayers = int64(maxPlayers)
	}
	status := strings.ToLower(strings.TrimSpace(req.Status))
	if status == "" {
		status = models.RegionStatusOnline
	}
	if status != models.RegionStatusOnline &&
		status != models.RegionStatusOffline &&
		status != models.RegionStatusMaintenance {
		status = models.RegionStatusOnline
	}

	webSocketURL := strings.TrimSpace(req.WebSocketURL)
	if webSocketURL == "" {
		webSocketURL = region.WebSocketURL
	}

	err := h.redis.SetRegionRuntimeStatus(
		r.Context(),
		&redisClient.RegionRuntimeStatus{
			RegionID:      regionID,
			ActivePlayers: activePlayers,
			MaxPlayers:    maxPlayers,
			WebSocketURL:  webSocketURL,
			Status:        status,
		},
		regionRuntimeStatusTTL,
	)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to update region status"})
		return
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]any{
		"status": "ok",
	})
}

// SelectRegion allows an authenticated user to select their game region
func (h *RegionHandler) SelectRegion(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	w.Header().Set("Content-Type", "application/json")

	// Get user claims from context (verify authentication)
	_, ok := middleware.GetUserClaims(r)
	if !ok {
		w.WriteHeader(http.StatusUnauthorized)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Unauthorized"})
		return
	}

	// Parse request body
	var req SelectRegionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid request body"})
		return
	}

	// Normalize region ID to lowercase
	req.RegionID = strings.ToLower(strings.TrimSpace(req.RegionID))

	// Validate region ID
	if !models.IsValidRegion(req.RegionID) {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{
			Error: "Invalid region. Valid regions are: local, asia, europe, us-west",
		})
		return
	}

	// Get region details
	region := models.GetRegionDetails(req.RegionID)
	if region == nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to get region details"})
		return
	}
	ctx := r.Context()
	heartbeatApplied := h.applyRuntimeStatuses(ctx, []*models.Region{region})

	// Check if region is available
	if !heartbeatApplied[region.ID] || region.Status != models.RegionStatusOnline {
		w.WriteHeader(http.StatusServiceUnavailable)
		json.NewEncoder(w).Encode(ErrorResponse{
			Error: "Selected region is currently unavailable",
		})
		return
	}

	// Check if region is full
	if region.ActivePlayers >= int64(region.MaxPlayers) {
		w.WriteHeader(http.StatusServiceUnavailable)
		json.NewEncoder(w).Encode(ErrorResponse{
			Error: "Selected region is currently full. Please try another region.",
		})
		return
	}

	// Extract token from Authorization header
	authHeader := r.Header.Get("Authorization")
	if authHeader == "" || !strings.HasPrefix(authHeader, "Bearer ") {
		w.WriteHeader(http.StatusUnauthorized)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Missing or invalid authorization header"})
		return
	}
	token := strings.TrimPrefix(authHeader, "Bearer ")

	// Update session with selected region
	// Note: We're updating the ServerRegion field, but CharacterID would be set when entering game
	if err := h.redis.UpdateSessionGameServer(ctx, token, 0, req.RegionID); err != nil {
		// Session might not exist yet, which is okay
		// Log the error but don't fail the request
		// In production, you might want to handle this differently
	}

	// Return success response with region details and WebSocket URL
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(SelectRegionResponse{
		Message:      "Region selected successfully",
		Region:       region,
		WebSocketURL: region.WebSocketURL,
	})
}

// onlineRegions keeps the regions whose game server has a fresh heartbeat (runtime status
// applied from Redis) and reports itself online. Game servers speak ENet/UDP (ADR 0003),
// so there is no TCP endpoint to probe — the 2 s heartbeat against the 5 s runtime-status
// TTL is the liveness signal.
func onlineRegions(regions []*models.Region, heartbeatApplied map[string]bool) []*models.Region {
	online := make([]*models.Region, 0, len(regions))
	for _, region := range regions {
		if heartbeatApplied[region.ID] && region.Status == models.RegionStatusOnline {
			online = append(online, region)
		}
	}
	return online
}

func (h *RegionHandler) applyRuntimeStatuses(ctx context.Context, regions []*models.Region) map[string]bool {
	applied := make(map[string]bool, len(regions))
	for _, region := range regions {
		status, err := h.redis.GetRegionRuntimeStatus(ctx, region.ID)
		if err != nil {
			continue
		}

		region.ActivePlayers = status.ActivePlayers
		if status.MaxPlayers > 0 {
			region.MaxPlayers = status.MaxPlayers
		}
		if status.WebSocketURL != "" {
			region.WebSocketURL = status.WebSocketURL
		}
		if status.Status != "" {
			region.Status = status.Status
		}
		applied[region.ID] = true
	}
	return applied
}
