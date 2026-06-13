package progression

import (
	"math"
	"testing"
)

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

// XPToNextLevel mirrors the Rust `xp_to_next_level`: the `level <= 1` branch
// covers 0 and (defensively) negative levels, returning the cheap first-level cost.
func TestXPToNextLevelLowAndNegative(t *testing.T) {
	if got := XPToNextLevel(0); got != XPFirstLevel {
		t.Errorf("XPToNextLevel(0) = %d, want %d", got, XPFirstLevel)
	}
	if got := XPToNextLevel(-5); got != XPFirstLevel {
		t.Errorf("XPToNextLevel(-5) = %d, want %d", got, XPFirstLevel)
	}
}

// At the cap, lifetime XP is the full sum of every prior level's cost (plus the
// in-level progress). 100 + 200*(2+3+...+49) = 100 + 200*1224 = 244900.
func TestTotalLifetimeXPAtMaxLevel(t *testing.T) {
	const wantLifetime = 244900
	if got := TotalLifetimeXP(MaxPlayerLevel, 0); got != wantLifetime {
		t.Errorf("TotalLifetimeXP(%d, 0) = %d, want %d", MaxPlayerLevel, got, wantLifetime)
	}
	// GloryFor at the cap = floor(244900 / 100) = 2449.
	if got := GloryFor(MaxPlayerLevel, 0); got != 2449 {
		t.Errorf("GloryFor(%d, 0) = %d, want 2449", MaxPlayerLevel, got)
	}
	// Experience past the cap level is discarded by the sim, but the math here is
	// total = priorLevels + experience; verify the sum still tracks experience.
	if got := TotalLifetimeXP(MaxPlayerLevel, 100); got != wantLifetime+100 {
		t.Errorf("TotalLifetimeXP(%d, 100) = %d, want %d", MaxPlayerLevel, got, wantLifetime+100)
	}
}

// GloryFor is floor(total lifetime XP / divisor): a total that does not divide
// evenly must round DOWN, never up.
func TestGloryForFloors(t *testing.T) {
	// Level 2 (100 lifetime) + 50 in-level = 150 lifetime => 150/100 floors to 1.
	if got := GloryFor(2, 50); got != 1 {
		t.Errorf("GloryFor(2, 50) = %d, want 1 (floored)", got)
	}
	// Level 2 (100 lifetime) + 99 in-level = 199 lifetime => still floors to 1.
	if got := GloryFor(2, 99); got != 1 {
		t.Errorf("GloryFor(2, 99) = %d, want 1 (floored)", got)
	}
	// One short of the divisor floors to 0.
	if got := GloryFor(1, 99); got != 0 {
		t.Errorf("GloryFor(1, 99) = %d, want 0 (floored)", got)
	}
}

// A near-max-int experience must not overflow or panic: TotalLifetimeXP/GloryFor
// accumulate in int64, which comfortably holds level prior-costs + a large int.
func TestGloryForLargeExperienceNoOverflow(t *testing.T) {
	const bigExp = math.MaxInt32 // 2147483647, the SMALLINT/INTEGER ceiling we'd ever store
	gotLifetime := TotalLifetimeXP(MaxPlayerLevel, bigExp)
	wantLifetime := int64(244900) + int64(bigExp)
	if gotLifetime != wantLifetime {
		t.Errorf("TotalLifetimeXP(%d, %d) = %d, want %d", MaxPlayerLevel, bigExp, gotLifetime, wantLifetime)
	}
	if got := GloryFor(MaxPlayerLevel, bigExp); got != wantLifetime/int64(GloryXPDivisor) {
		t.Errorf("GloryFor(%d, %d) = %d, want %d", MaxPlayerLevel, bigExp, got, wantLifetime/int64(GloryXPDivisor))
	}
}
