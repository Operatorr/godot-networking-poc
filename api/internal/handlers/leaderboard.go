package handlers

import (
	"encoding/json"
	"net/http"

	"github.com/omega-realm/api/internal/database"
)

type LeaderboardHandler struct {
	db *database.DB
}

func NewLeaderboardHandler(db *database.DB) *LeaderboardHandler {
	return &LeaderboardHandler{db: db}
}

func (h *LeaderboardHandler) GetLeaderboard(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{
		"message": "Get leaderboard endpoint - TODO: implement",
	})
}

func (h *LeaderboardHandler) UpdateLeaderboard(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{
		"message": "Update leaderboard endpoint - TODO: implement",
	})
}
