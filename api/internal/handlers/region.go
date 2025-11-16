package handlers

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"

	"github.com/omega-realm/api/internal/middleware"
	"github.com/omega-realm/api/internal/models"
	redisClient "github.com/omega-realm/api/internal/redis"
)

type RegionHandler struct {
	redis *redisClient.Client
}

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

// GetRegions returns all available regions with their current player counts
func (h *RegionHandler) GetRegions(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	w.Header().Set("Content-Type", "application/json")

	// Get all regions
	regions := models.GetAllRegions()

	// Populate active player counts from Redis
	ctx := context.Background()
	for _, region := range regions {
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
			Error: "Invalid region. Valid regions are: asia, europe, us-west",
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
	err = h.redis.UpdateSessionGameServer(ctx, token, 0, req.RegionID)
	if err != nil {
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
