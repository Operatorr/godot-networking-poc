package handlers

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"

	"github.com/omega-realm/api/internal/database"
	"github.com/omega-realm/api/internal/middleware"
	"github.com/omega-realm/api/internal/models"
	"github.com/omega-realm/api/internal/progression"
)

type CharacterHandler struct {
	db *database.DB
}

func NewCharacterHandler(db *database.DB) *CharacterHandler {
	return &CharacterHandler{db: db}
}

// CreateCharacterRequest represents the request body for character creation
type CreateCharacterRequest struct {
	Name  string `json:"name"`
	Class string `json:"class"`
	Race  string `json:"race"`
	Realm string `json:"realm"`
	Mode  string `json:"mode"`
	Level int    `json:"level"`
}

// CharacterSuccessResponse represents a success response with character data
type CharacterSuccessResponse struct {
	Message   string            `json:"message"`
	Character *models.Character `json:"character"`
}

// GetCharacter returns the authenticated user's character
func (h *CharacterHandler) GetCharacter(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	// Get user claims from context
	claims, ok := middleware.GetUserClaims(r)
	if !ok {
		w.WriteHeader(http.StatusUnauthorized)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Unauthorized"})
		return
	}

	// Query character by user_id
	var character models.Character
	query := `
		SELECT id, user_id, name, class, race, realm, mode, level, experience, created_at
		FROM characters
		WHERE user_id = $1
	`
	err := h.db.QueryRow(query, claims.UserID).Scan(
		&character.ID,
		&character.UserID,
		&character.Name,
		&character.Class,
		&character.Race,
		&character.Realm,
		&character.Mode,
		&character.Level,
		&character.Experience,
		&character.CreatedAt,
	)

	if err == sql.ErrNoRows {
		w.WriteHeader(http.StatusNotFound)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "No character found for this user"})
		return
	}

	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to fetch character"})
		return
	}

	// Fetch account-wide Glory (best-effort: default to 0 if the user row is
	// missing rather than failing the whole request).
	var glory int
	if err := h.db.QueryRow(`SELECT glory FROM users WHERE id = $1`, claims.UserID).Scan(&glory); err != nil {
		glory = 0
	}

	// Marshal the character to a generic map so we can add the top-level
	// "glory" field without changing the existing character fields.
	characterJSON, err := json.Marshal(character)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to encode character"})
		return
	}
	var response map[string]interface{}
	if err := json.Unmarshal(characterJSON, &response); err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to encode character"})
		return
	}
	response["glory"] = glory

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(response)
}

// CreateCharacter creates a new character for the authenticated user
func (h *CharacterHandler) CreateCharacter(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	w.Header().Set("Content-Type", "application/json")

	// Get user claims from context
	claims, ok := middleware.GetUserClaims(r)
	if !ok {
		w.WriteHeader(http.StatusUnauthorized)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Unauthorized"})
		return
	}

	// Parse request body
	var req CreateCharacterRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid request body"})
		return
	}

	// Validate character name
	if err := validateCharacterName(req.Name); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: err.Error()})
		return
	}
	normalizeCharacterRequest(&req)
	if err := validateCharacterOptions(req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: err.Error()})
		return
	}

	// Check if user already has a character
	var existingCharacterID int
	checkQuery := `SELECT id FROM characters WHERE user_id = $1`
	err := h.db.QueryRow(checkQuery, claims.UserID).Scan(&existingCharacterID)

	if err == nil {
		// Character exists
		w.WriteHeader(http.StatusConflict)
		json.NewEncoder(w).Encode(map[string]string{
			"error": "User already has a character",
			"code":  "character_exists",
		})
		return
	} else if err != sql.ErrNoRows {
		// Database error
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to check existing character"})
		return
	}

	// Insert new character
	var character models.Character
	insertQuery := `
		INSERT INTO characters (user_id, name, class, race, realm, mode, level)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
		RETURNING id, user_id, name, class, race, realm, mode, level, experience, created_at
	`
	err = h.db.QueryRow(
		insertQuery,
		claims.UserID,
		req.Name,
		req.Class,
		req.Race,
		req.Realm,
		req.Mode,
		req.Level,
	).Scan(
		&character.ID,
		&character.UserID,
		&character.Name,
		&character.Class,
		&character.Race,
		&character.Realm,
		&character.Mode,
		&character.Level,
		&character.Experience,
		&character.CreatedAt,
	)

	if err != nil {
		// Check if it's a unique constraint violation
		if strings.Contains(err.Error(), "duplicate key") {
			if strings.Contains(err.Error(), "characters_name_key") {
				w.WriteHeader(http.StatusConflict)
				json.NewEncoder(w).Encode(ErrorResponse{Error: "Character name already taken"})
				return
			}
			if strings.Contains(err.Error(), "characters_user_id_key") {
				w.WriteHeader(http.StatusConflict)
				json.NewEncoder(w).Encode(map[string]string{
					"error": "User already has a character",
					"code":  "character_exists",
				})
				return
			}
		}
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to create character"})
		return
	}

	// Return success response
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(CharacterSuccessResponse{
		Message:   "Character created successfully",
		Character: &character,
	})
}

// Character progression (level + experience) is server-authoritative: it is written
// ONLY by the Rust game server via the X-Server-Token internal endpoints
// (POST /api/internal/characters/{id}/progress). There is deliberately no
// JWT/client-writable progression endpoint — that would let a modified client set its
// own level/XP and then sacrifice it for Glory.

// DeleteCharacter removes the authenticated user's character. Leaderboard and
// session rows are removed automatically via ON DELETE CASCADE foreign keys.
func (h *CharacterHandler) DeleteCharacter(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	// Get user claims from context
	claims, ok := middleware.GetUserClaims(r)
	if !ok {
		w.WriteHeader(http.StatusUnauthorized)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Unauthorized"})
		return
	}

	result, err := h.db.Exec(`DELETE FROM characters WHERE user_id = $1`, claims.UserID)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to delete character"})
		return
	}

	rows, err := result.RowsAffected()
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to delete character"})
		return
	}
	if rows == 0 {
		w.WriteHeader(http.StatusNotFound)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "No character found for this user"})
		return
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]string{"message": "Character deleted"})
}

// SacrificeResponse is the body returned by SacrificeCharacter.
type SacrificeResponse struct {
	GloryAwarded int64 `json:"glory_awarded"`
}

// SacrificeCharacter is the player-initiated church sacrifice: the authenticated
// user trades their living character for account-wide Glory. Atomic: read the
// character's level/experience, award floor(lifetime XP / divisor) Glory to the
// account, then delete the character. 404 if the user has no character.
//
// POST /api/character/sacrifice (JWT-protected)
func (h *CharacterHandler) SacrificeCharacter(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	claims, ok := middleware.GetUserClaims(r)
	if !ok {
		w.WriteHeader(http.StatusUnauthorized)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Unauthorized"})
		return
	}

	tx, err := h.db.Begin()
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to start transaction"})
		return
	}
	defer tx.Rollback() //nolint:errcheck // no-op after a successful Commit

	var level, experience int
	err = tx.QueryRow(
		`SELECT level, experience FROM characters WHERE user_id = $1 FOR UPDATE`, claims.UserID,
	).Scan(&level, &experience)
	if err == sql.ErrNoRows {
		w.WriteHeader(http.StatusNotFound)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "No character found for this user"})
		return
	}
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to fetch character"})
		return
	}

	glory := progression.GloryFor(level, experience)
	if _, err := tx.Exec(
		`UPDATE users SET glory = glory + $1 WHERE id = $2`, glory, claims.UserID,
	); err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to award glory"})
		return
	}

	if _, err := tx.Exec(`DELETE FROM characters WHERE user_id = $1`, claims.UserID); err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to delete character"})
		return
	}

	if err := tx.Commit(); err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to commit transaction"})
		return
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(SacrificeResponse{GloryAwarded: glory})
}

func normalizeCharacterRequest(req *CreateCharacterRequest) {
	req.Class = defaultString(strings.TrimSpace(req.Class), "Warrior")
	req.Race = defaultString(strings.TrimSpace(req.Race), "Human")
	req.Realm = defaultString(strings.TrimSpace(req.Realm), "Asia (Singapore)")
	req.Mode = defaultString(strings.TrimSpace(req.Mode), "softcore")
	if req.Level == 0 {
		req.Level = 1
	}
}

func defaultString(value, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}

func validateCharacterOptions(req CreateCharacterRequest) error {
	if len(req.Class) > 20 {
		return fmt.Errorf("character class must not exceed 20 characters")
	}
	if len(req.Race) > 20 {
		return fmt.Errorf("character race must not exceed 20 characters")
	}
	if len(req.Realm) > 50 {
		return fmt.Errorf("character realm must not exceed 50 characters")
	}
	if len(req.Mode) > 20 {
		return fmt.Errorf("character mode must not exceed 20 characters")
	}
	if req.Level < 1 || req.Level > progression.MaxPlayerLevel {
		return fmt.Errorf("character level must be between 1 and %d", progression.MaxPlayerLevel)
	}
	return nil
}

// validateCharacterName validates the character name
func validateCharacterName(name string) error {
	// Trim whitespace
	name = strings.TrimSpace(name)

	// Check length
	if len(name) < 3 {
		return fmt.Errorf("character name must be at least 3 characters long")
	}
	if len(name) > 50 {
		return fmt.Errorf("character name must not exceed 50 characters")
	}

	// Check for valid characters (alphanumeric, spaces, underscores, hyphens)
	for _, char := range name {
		if !isValidCharacterNameChar(char) {
			return fmt.Errorf("character name contains invalid characters. Only letters, numbers, spaces, underscores, and hyphens are allowed")
		}
	}

	// Check that it doesn't start or end with whitespace
	if name != strings.TrimSpace(name) {
		return fmt.Errorf("character name cannot start or end with whitespace")
	}

	return nil
}

// isValidCharacterNameChar checks if a character is valid for character names
func isValidCharacterNameChar(char rune) bool {
	return (char >= 'a' && char <= 'z') ||
		(char >= 'A' && char <= 'Z') ||
		(char >= '0' && char <= '9') ||
		char == ' ' ||
		char == '_' ||
		char == '-'
}
