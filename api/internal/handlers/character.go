package handlers

import (
	"encoding/json"
	"net/http"

	"github.com/omega-realm/api/internal/database"
)

type CharacterHandler struct {
	db *database.DB
}

func NewCharacterHandler(db *database.DB) *CharacterHandler {
	return &CharacterHandler{db: db}
}

func (h *CharacterHandler) GetCharacters(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{
		"message": "Get characters endpoint - TODO: implement",
	})
}

func (h *CharacterHandler) CreateCharacter(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{
		"message": "Create character endpoint - TODO: implement",
	})
}
