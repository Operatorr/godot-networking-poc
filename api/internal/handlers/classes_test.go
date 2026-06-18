package handlers

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

// writeClassFixture lays out a minimal classes/ tree (index.json + per-class
// files) under a temp dir and returns the content root to point a handler at.
func writeClassFixture(t *testing.T, index string, files map[string]string) string {
	t.Helper()
	root := t.TempDir()
	classesDir := filepath.Join(root, "classes")
	if err := os.MkdirAll(classesDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(classesDir, "index.json"), []byte(index), 0o644); err != nil {
		t.Fatal(err)
	}
	for name, body := range files {
		if err := os.WriteFile(filepath.Join(classesDir, name), []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return root
}

func getClasses(t *testing.T, h *ClassHandler) []ClassOption {
	t.Helper()
	req := httptest.NewRequest(http.MethodGet, "/api/classes", nil)
	rec := httptest.NewRecorder()
	h.GetClasses(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	var body struct {
		Classes []ClassOption `json:"classes"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	return body.Classes
}

func TestGetClassesReadsPlayableInIndexOrder(t *testing.T) {
	root := writeClassFixture(t,
		`{"playable":["warrior","rogue","mage"]}`,
		map[string]string{
			"warrior.json": `{"display_name":"Warrior"}`,
			"rogue.json":   `{"display_name":"Rogue"}`,
			"mage.json":    `{"display_name":"Mage"}`,
		},
	)
	h := &ClassHandler{contentDir: root}

	got := getClasses(t, h)
	want := []ClassOption{
		{ID: "warrior", DisplayName: "Warrior"},
		{ID: "rogue", DisplayName: "Rogue"},
		{ID: "mage", DisplayName: "Mage"},
	}
	if len(got) != len(want) {
		t.Fatalf("got %d classes, want %d: %v", len(got), len(want), got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("class %d = %+v, want %+v", i, got[i], want[i])
		}
	}
}

func TestGetClassesIgnoresNonPlayable(t *testing.T) {
	// "void_hunter" is defined but not in playable — it must not appear.
	root := writeClassFixture(t,
		`{"classes":["void_hunter","rogue"],"playable":["rogue"]}`,
		map[string]string{
			"rogue.json":       `{"display_name":"Rogue"}`,
			"void_hunter.json": `{"display_name":"Void Hunter"}`,
		},
	)
	h := &ClassHandler{contentDir: root}

	got := getClasses(t, h)
	if len(got) != 1 || got[0].ID != "rogue" {
		t.Fatalf("expected only [rogue], got %v", got)
	}
}

func TestGetClassesFallsBackToDefaultWhenUnreadable(t *testing.T) {
	// Point at a dir with no classes/ tree: handler must still serve the default.
	h := &ClassHandler{contentDir: t.TempDir()}

	got := getClasses(t, h)
	if len(got) != len(defaultPlayableClasses) {
		t.Fatalf("expected %d default classes, got %v", len(defaultPlayableClasses), got)
	}
	if got[1] != (ClassOption{ID: "rogue", DisplayName: "Rogue"}) {
		t.Errorf("expected Rogue in the default set, got %v", got)
	}
}

func TestGetClassesTitleCasesMissingDisplayName(t *testing.T) {
	// A playable id whose file is missing falls back to a title-cased id.
	root := writeClassFixture(t,
		`{"playable":["rogue"]}`,
		map[string]string{}, // no rogue.json
	)
	h := &ClassHandler{contentDir: root}

	got := getClasses(t, h)
	if len(got) != 1 || got[0] != (ClassOption{ID: "rogue", DisplayName: "Rogue"}) {
		t.Fatalf("expected [{rogue Rogue}], got %v", got)
	}
}
