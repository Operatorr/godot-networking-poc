package handlers

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/omega-realm/api/internal/middleware"
	"github.com/omega-realm/api/internal/models"
	redisClient "github.com/omega-realm/api/internal/redis"
)

type RegionHandler struct {
	redis *redisClient.Client
}

const regionProbeTimeout = 500 * time.Millisecond
const regionRuntimeStatusTTL = 5 * time.Second

var dialTCP = net.DialTimeout

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
	runtimeRegions := h.applyRuntimeStatuses(context.Background(), regions)

	// Probe game servers and only return regions that are currently reachable.
	regions = h.getOnlineRegions(regions)

	// Populate active player counts from Redis for online regions.
	ctx := context.Background()
	for _, region := range regions {
		if runtimeRegions[region.ID] {
			continue
		}
		count, err := h.redis.GetActiveUsersByRegion(ctx, region.ID)
		if err != nil {
			// If Redis fails, default to 0 active players
			count = 0
		}
		region.ActivePlayers = count
	}

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

	if expectedToken := os.Getenv("REGION_HEARTBEAT_TOKEN"); expectedToken != "" {
		if r.Header.Get("X-Region-Heartbeat-Token") != expectedToken {
			w.WriteHeader(http.StatusUnauthorized)
			json.NewEncoder(w).Encode(ErrorResponse{Error: "Unauthorized"})
			return
		}
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
	runtimeRegions := h.applyRuntimeStatuses(context.Background(), []*models.Region{region})
	h.updateRegionAvailability(region)

	// Check if region is available
	if region.Status != models.RegionStatusOnline {
		w.WriteHeader(http.StatusServiceUnavailable)
		json.NewEncoder(w).Encode(ErrorResponse{
			Error: "Selected region is currently unavailable",
		})
		return
	}

	// Get active player count
	ctx := context.Background()
	if runtimeRegions[region.ID] {
		if region.ActivePlayers >= int64(region.MaxPlayers) {
			w.WriteHeader(http.StatusServiceUnavailable)
			json.NewEncoder(w).Encode(ErrorResponse{
				Error: "Selected region is currently full. Please try another region.",
			})
			return
		}
	} else {
		activeCount, err := h.redis.GetActiveUsersByRegion(ctx, req.RegionID)
		if err == nil {
			region.ActivePlayers = activeCount

			// Check if region is full
			if activeCount >= int64(region.MaxPlayers) {
				w.WriteHeader(http.StatusServiceUnavailable)
				json.NewEncoder(w).Encode(ErrorResponse{
					Error: "Selected region is currently full. Please try another region.",
				})
				return
			}
		}
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

func (h *RegionHandler) getOnlineRegions(regions []*models.Region) []*models.Region {
	var wg sync.WaitGroup
	for _, region := range regions {
		wg.Add(1)
		go func(region *models.Region) {
			defer wg.Done()
			h.updateRegionAvailability(region)
		}(region)
	}
	wg.Wait()

	onlineRegions := make([]*models.Region, 0, len(regions))
	for _, region := range regions {
		if region.Status == models.RegionStatusOnline {
			onlineRegions = append(onlineRegions, region)
		}
	}

	return onlineRegions
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

func (h *RegionHandler) updateRegionAvailability(region *models.Region) {
	if isWebSocketServerOnline(region.WebSocketURL, regionProbeTimeout) {
		region.Status = models.RegionStatusOnline
		return
	}
	region.Status = models.RegionStatusOffline
}

func isWebSocketServerOnline(webSocketURL string, timeout time.Duration) bool {
	parsedURL, err := url.Parse(webSocketURL)
	if err != nil {
		return false
	}
	if parsedURL.Scheme != "ws" && parsedURL.Scheme != "wss" {
		return false
	}

	hostName := parsedURL.Hostname()
	if hostName == "" {
		return false
	}
	port := parsedURL.Port()
	if port == "" {
		switch parsedURL.Scheme {
		case "ws":
			port = "80"
		case "wss":
			port = "443"
		default:
			return false
		}
	}

	host := net.JoinHostPort(hostName, port)
	conn, err := dialTCP("tcp", host, timeout)
	if err != nil {
		return false
	}
	_ = conn.Close()
	return true
}
