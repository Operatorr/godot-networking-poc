// Package progression ports the shared level curve and Glory conversion math from
// rust/sim_core/src/progression.rs. This port MUST produce identical results for
// all valid (non-negative, in-range) inputs as the Rust authoritative server, so
// that death/sacrifice Glory awards computed by the Go API match what the
// simulation expects.
//
// Reference: rust/sim_core/src/progression.rs (the source of truth).
package progression

const (
	// MaxPlayerLevel is the level cap. At or above it, XP stops accruing.
	MaxPlayerLevel = 50

	// XPFirstLevel is the XP to go from level 1 -> 2 (a deliberately-cheap first level).
	XPFirstLevel = 100

	// XPLevelSlope is the slope for level L -> L+1 (L >= 2): XPLevelSlope * L.
	XPLevelSlope = 200

	// GloryXPDivisor: Glory = floor(total lifetime XP / GloryXPDivisor).
	GloryXPDivisor = 100
)

// XPToNextLevel returns the XP required to advance FROM level to the next level.
// 0 at (or above) the cap; XPFirstLevel for level <= 1.
func XPToNextLevel(level int) int {
	if level >= MaxPlayerLevel {
		return 0
	}
	if level <= 1 {
		return XPFirstLevel
	}
	return XPLevelSlope * level
}

// TotalLifetimeXP returns the total lifetime XP a character at (level, experience)
// has earned: the sum of every prior level's cost (capped at MaxPlayerLevel) plus
// the current in-level progress.
func TotalLifetimeXP(level, experience int) int64 {
	total := int64(experience)
	for l := 1; l < level && l < MaxPlayerLevel; l++ {
		total += int64(XPToNextLevel(l))
	}
	return total
}

// GloryFor returns the Glory awarded when a character at (level, experience) dies
// (hardcore) or is sacrificed (softcore): floor(TotalLifetimeXP / GloryXPDivisor).
func GloryFor(level, experience int) int64 {
	return TotalLifetimeXP(level, experience) / int64(GloryXPDivisor)
}
