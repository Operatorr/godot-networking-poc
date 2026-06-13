package handlers

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"os"
	"strconv"

	"github.com/omega-realm/api/internal/database"
	"github.com/omega-realm/api/internal/progression"
)

// InternalHandler serves server-only endpoints used by the authoritative Rust game
// server to read and write character progression and to settle Glory on death. These
// routes are NOT JWT-protected; they are guarded by a shared server token instead
// (header X-Server-Token vs env SERVER_API_TOKEN), mirroring the region heartbeat.
type InternalHandler struct {
	db *database.DB
}

// NewInternalHandler constructs an InternalHandler.
func NewInternalHandler(db *database.DB) *InternalHandler {
	return &InternalHandler{db: db}
}

// requireServerToken validates the X-Server-Token header against SERVER_API_TOKEN.
// Mirroring the region heartbeat (REGION_HEARTBEAT_TOKEN) behavior: when the env var
// is empty the check is skipped (dev parity). When set, a mismatch is rejected 401.
// Returns true if the request may proceed.
func requireServerToken(w http.ResponseWriter, r *http.Request) bool {
	if expectedToken := os.Getenv("SERVER_API_TOKEN"); expectedToken != "" {
		if r.Header.Get("X-Server-Token") != expectedToken {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusUnauthorized)
			json.NewEncoder(w).Encode(ErrorResponse{Error: "Unauthorized"})
			return false
		}
	}
	return true
}

// CharacterProgressResponse is the body returned by GetCharacter.
type CharacterProgressResponse struct {
	Level      int    `json:"level"`
	Experience int    `json:"experience"`
	Mode       string `json:"mode"`
}

// ProgressRequest is the body for the progress-update endpoint.
type ProgressRequest struct {
	Level      int `json:"level"`
	Experience int `json:"experience"`
}

// DeathResponse is the body returned by the death endpoint.
type DeathResponse struct {
	GloryAwarded     int64 `json:"glory_awarded"`
	CharacterDeleted bool  `json:"character_deleted"`
}

// GetCharacter returns level/experience/mode for the character with the given id
// (the characters.id primary key, NOT user_id). 404 if missing.
//
// GET /api/internal/characters/{id}
func (h *InternalHandler) GetCharacter(w http.ResponseWriter, r *http.Request) {
	if !requireServerToken(w, r) {
		return
	}
	w.Header().Set("Content-Type", "application/json")
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	id, ok := parsePathID(w, r)
	if !ok {
		return
	}

	var resp CharacterProgressResponse
	err := h.db.QueryRow(
		`SELECT level, experience, mode FROM characters WHERE id = $1`, id,
	).Scan(&resp.Level, &resp.Experience, &resp.Mode)
	if err == sql.ErrNoRows {
		w.WriteHeader(http.StatusNotFound)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Character not found"})
		return
	}
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to fetch character"})
		return
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(resp)
}

// UpdateProgress writes level + experience for the character with the given id.
// Level is clamped to 1..MaxPlayerLevel and experience to >= 0.
//
// POST /api/internal/characters/{id}/progress
func (h *InternalHandler) UpdateProgress(w http.ResponseWriter, r *http.Request) {
	if !requireServerToken(w, r) {
		return
	}
	w.Header().Set("Content-Type", "application/json")
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	id, ok := parsePathID(w, r)
	if !ok {
		return
	}

	var req ProgressRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid request body"})
		return
	}

	level := req.Level
	if level < 1 {
		level = 1
	}
	if level > progression.MaxPlayerLevel {
		level = progression.MaxPlayerLevel
	}
	experience := req.Experience
	if experience < 0 {
		experience = 0
	}

	result, err := h.db.Exec(
		`UPDATE characters SET level = $1, experience = $2 WHERE id = $3`,
		level, experience, id,
	)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to update character"})
		return
	}
	rows, _ := result.RowsAffected()
	if rows == 0 {
		w.WriteHeader(http.StatusNotFound)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Character not found"})
		return
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]bool{"ok": true})
}

// Death settles a character death atomically: read the character's level,
// experience, mode and user_id; award Glory (floor of lifetime XP / divisor) to the
// owning account; and for hardcore characters delete the character (permadeath).
// Softcore characters are left in place.
//
// POST /api/internal/characters/{id}/death
func (h *InternalHandler) Death(w http.ResponseWriter, r *http.Request) {
	if !requireServerToken(w, r) {
		return
	}
	w.Header().Set("Content-Type", "application/json")
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	id, ok := parsePathID(w, r)
	if !ok {
		return
	}

	tx, err := h.db.Begin()
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to start transaction"})
		return
	}
	defer tx.Rollback() //nolint:errcheck // no-op after a successful Commit

	var (
		level      int
		experience int
		mode       string
		userID     int
	)
	err = tx.QueryRow(
		`SELECT level, experience, mode, user_id FROM characters WHERE id = $1 FOR UPDATE`, id,
	).Scan(&level, &experience, &mode, &userID)
	if err == sql.ErrNoRows {
		w.WriteHeader(http.StatusNotFound)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Character not found"})
		return
	}
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to fetch character"})
		return
	}

	glory := progression.GloryFor(level, experience)
	if _, err := tx.Exec(
		`UPDATE users SET glory = glory + $1 WHERE id = $2`, glory, userID,
	); err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to award glory"})
		return
	}

	characterDeleted := false
	if mode == "hardcore" {
		if _, err := tx.Exec(`DELETE FROM characters WHERE id = $1`, id); err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to delete character"})
			return
		}
		characterDeleted = true
	}

	if err := tx.Commit(); err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to commit transaction"})
		return
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(DeathResponse{
		GloryAwarded:     glory,
		CharacterDeleted: characterDeleted,
	})
}

// parsePathID reads and validates the {id} path value. On error it writes a 400 and
// returns ok=false.
func parsePathID(w http.ResponseWriter, r *http.Request) (int, bool) {
	idStr := r.PathValue("id")
	id, err := strconv.Atoi(idStr)
	if err != nil || id <= 0 {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid character id"})
		return 0, false
	}
	return id, true
}
