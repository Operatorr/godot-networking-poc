package progression

import "testing"

func TestGloryFor(t *testing.T) {
	// Level 2 with 0 in-level XP => 100 lifetime XP => 1 Glory.
	if got := GloryFor(2, 0); got != 1 {
		t.Errorf("GloryFor(2, 0) = %d, want 1", got)
	}
	// Level 3 with 0 in-level XP => 100 + 400 = 500 lifetime XP => 5 Glory.
	if got := GloryFor(3, 0); got != 5 {
		t.Errorf("GloryFor(3, 0) = %d, want 5", got)
	}
}

func TestTotalLifetimeXP(t *testing.T) {
	if got := TotalLifetimeXP(2, 0); got != 100 {
		t.Errorf("TotalLifetimeXP(2, 0) = %d, want 100", got)
	}
	if got := TotalLifetimeXP(3, 0); got != 500 {
		t.Errorf("TotalLifetimeXP(3, 0) = %d, want 500", got)
	}
}

func TestXPToNextLevel(t *testing.T) {
	if got := XPToNextLevel(1); got != 100 {
		t.Errorf("XPToNextLevel(1) = %d, want 100", got)
	}
	if got := XPToNextLevel(2); got != 400 {
		t.Errorf("XPToNextLevel(2) = %d, want 400", got)
	}
	if got := XPToNextLevel(MaxPlayerLevel); got != 0 {
		t.Errorf("XPToNextLevel(%d) = %d, want 0", MaxPlayerLevel, got)
	}
}
