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
)

type CharacterHandler struct {
	db *database.DB
}

func NewCharacterHandler(db *database.DB) *CharacterHandler {
	return &CharacterHandler{db: db}
}

// CreateCharacterRequest represents the request body for character creation
type CreateCharacterRequest struct {
	Name string `json:"name"`
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
	query := `SELECT id, user_id, name, created_at FROM characters WHERE user_id = $1`
	err := h.db.QueryRow(query, claims.UserID).Scan(
		&character.ID,
		&character.UserID,
		&character.Name,
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

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(character)
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

	// Check if user already has a character
	var existingCharacterID int
	checkQuery := `SELECT id FROM characters WHERE user_id = $1`
	err := h.db.QueryRow(checkQuery, claims.UserID).Scan(&existingCharacterID)

	if err == nil {
		// Character exists
		w.WriteHeader(http.StatusConflict)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "User already has a character"})
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
		INSERT INTO characters (user_id, name)
		VALUES ($1, $2)
		RETURNING id, user_id, name, created_at
	`
	err = h.db.QueryRow(insertQuery, claims.UserID, req.Name).Scan(
		&character.ID,
		&character.UserID,
		&character.Name,
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
				json.NewEncoder(w).Encode(ErrorResponse{Error: "User already has a character"})
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
