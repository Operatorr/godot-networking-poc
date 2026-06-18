package handlers

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
)

// ClassHandler serves the curated, PLAYABLE player-class list the website's
// character-creation form renders. It is read-only and public (no auth): the
// data is not sensitive and the dropdown must work before a character exists.
//
// Source of truth is the game JSON the Rust server also consumes —
// client/data/classes/index.json (the `playable` array, in wire-enum order)
// plus each <id>.json for its display_name. This keeps the website in lockstep
// with the game instead of a hand-maintained constant. If the files are
// unreadable (e.g. the game repo isn't on disk), it falls back to the
// pre-alpha-scope default so the form never breaks.
type ClassHandler struct {
	// contentDir is the game-content root (the dir holding classes/). Resolved
	// once at construction; see resolveContentDir.
	contentDir string
}

func NewClassHandler() *ClassHandler {
	return &ClassHandler{contentDir: resolveContentDir()}
}

// resolveContentDir mirrors the web CMS's GAME_CONTENT_DIR convention: an
// explicit override, else the game repo's client/data sitting next to the api/
// working directory on the droplet (ADR 0007 native deploy:
// /home/deploy/omega-realm/{api,client}).
func resolveContentDir() string {
	if override := os.Getenv("GAME_CONTENT_DIR"); override != "" {
		return override
	}
	return filepath.Join("..", "client", "data")
}

// ClassOption is one selectable class: the stored value (display_name, matching
// the characters.class column's existing values) plus its id for reference.
type ClassOption struct {
	ID          string `json:"id"`
	DisplayName string `json:"display_name"`
}

// defaultPlayableClasses is the pre-alpha scope gate, used when the game JSON
// can't be read. Mirrors client/data/classes/index.json `playable`.
var defaultPlayableClasses = []ClassOption{
	{ID: "warrior", DisplayName: "Warrior"},
	{ID: "rogue", DisplayName: "Rogue"},
	{ID: "mage", DisplayName: "Mage"},
}

// classesIndex is the shape of client/data/classes/index.json we care about.
type classesIndex struct {
	Playable []string `json:"playable"`
}

// classDefinition is the slice of <id>.json we read for the dropdown label.
type classDefinition struct {
	DisplayName string `json:"display_name"`
}

// GetClasses returns the playable classes in wire-enum order. Always 200 with a
// non-empty list (falls back to the built-in default on any read error).
func (h *ClassHandler) GetClasses(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"classes": h.playableClasses(),
	})
}

// playableClasses reads the index + per-class display names from the game JSON,
// preserving the index's order. Returns the built-in default if the index or
// every class file is unreadable.
func (h *ClassHandler) playableClasses() []ClassOption {
	classesDir := filepath.Join(h.contentDir, "classes")

	raw, err := os.ReadFile(filepath.Join(classesDir, "index.json"))
	if err != nil {
		return defaultPlayableClasses
	}
	var idx classesIndex
	if err := json.Unmarshal(raw, &idx); err != nil || len(idx.Playable) == 0 {
		return defaultPlayableClasses
	}

	out := make([]ClassOption, 0, len(idx.Playable))
	for _, id := range idx.Playable {
		display := displayNameFor(classesDir, id)
		out = append(out, ClassOption{ID: id, DisplayName: display})
	}
	if len(out) == 0 {
		return defaultPlayableClasses
	}
	return out
}

// displayNameFor reads classes/<id>.json's display_name, falling back to a
// title-cased id if the file is missing or lacks the field.
func displayNameFor(classesDir, id string) string {
	raw, err := os.ReadFile(filepath.Join(classesDir, id+".json"))
	if err == nil {
		var def classDefinition
		if json.Unmarshal(raw, &def) == nil && def.DisplayName != "" {
			return def.DisplayName
		}
	}
	return titleCase(id)
}

// titleCase upper-cases the first rune of an ascii id ("rogue" -> "Rogue").
func titleCase(s string) string {
	if s == "" {
		return s
	}
	b := []byte(s)
	if b[0] >= 'a' && b[0] <= 'z' {
		b[0] -= 'a' - 'A'
	}
	return string(b)
}
