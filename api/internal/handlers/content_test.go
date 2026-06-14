package handlers

import (
	"testing"

	"github.com/omega-realm/api/internal/content"
)

// TestParseKind exercises the kind-validation helper that gates every CMS route.
// It is DB-free: it only checks that the closed Kind set is accepted and unknown
// segments are rejected. Anything needing a live DB (admin check, store calls) is
// covered by integration tests, not here.
func TestParseKind(t *testing.T) {
	valid := []string{"monsters", "classes", "weapons", "spells", "projectiles", "balance"}
	for _, raw := range valid {
		kind, ok := content.ParseKind(raw)
		if !ok {
			t.Errorf("ParseKind(%q) ok = false, want true", raw)
		}
		if string(kind) != raw {
			t.Errorf("ParseKind(%q) kind = %q, want %q", raw, kind, raw)
		}
	}

	invalid := []string{"", "enemy", "item", "spell", "Monsters", "monsters ", "monster", "balanc", "weapon"}
	for _, raw := range invalid {
		if _, ok := content.ParseKind(raw); ok {
			t.Errorf("ParseKind(%q) ok = true, want false", raw)
		}
	}
}

// TestContentIDPattern locks the slug rule UpsertDefinition enforces before an id
// reaches the store (and ultimately the published artifact path / in-game key).
func TestContentIDPattern(t *testing.T) {
	good := []string{"goblin", "fire_ball", "spell-01", "AB_cd-12", "X"}
	for _, id := range good {
		if !contentIDPattern.MatchString(id) {
			t.Errorf("contentIDPattern rejected valid id %q", id)
		}
	}

	bad := []string{"", "has space", "slash/here", "dot.json", "emoji😀", "a;b", "../etc"}
	for _, id := range bad {
		if contentIDPattern.MatchString(id) {
			t.Errorf("contentIDPattern accepted invalid id %q", id)
		}
	}
}
