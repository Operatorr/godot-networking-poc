package handlers

import "testing"

func TestLeaderboardColumnResolvesAllowlistedMetrics(t *testing.T) {
	cases := map[string]string{
		"":              "pvp_kills", // empty falls back to the default metric
		"pvp_kills":     "pvp_kills",
		"monster_kills": "monster_kills",
		"deaths":        "deaths",
	}
	for metric, wantColumn := range cases {
		column, ok := leaderboardColumn(metric)
		if !ok {
			t.Errorf("leaderboardColumn(%q): expected ok, got rejected", metric)
			continue
		}
		if column != wantColumn {
			t.Errorf("leaderboardColumn(%q) = %q, want %q", metric, column, wantColumn)
		}
	}
}

func TestLeaderboardColumnRejectsUnknownMetric(t *testing.T) {
	// An unknown metric must be rejected so it can never reach the ORDER BY clause.
	for _, metric := range []string{"id", "username", "pvp_kills; DROP TABLE users", "level"} {
		if _, ok := leaderboardColumn(metric); ok {
			t.Errorf("leaderboardColumn(%q): expected rejection, got accepted", metric)
		}
	}
}

func TestClampLeaderboardLimit(t *testing.T) {
	cases := map[string]int{
		"":     defaultLeaderboardLimit, // empty -> default
		"abc":  defaultLeaderboardLimit, // unparseable -> default
		"0":    defaultLeaderboardLimit, // below 1 -> default
		"-5":   defaultLeaderboardLimit, // negative -> default
		"1":    1,
		"25":   25,
		"100":  100,
		"101":  maxLeaderboardLimit, // above cap -> clamped
		"5000": maxLeaderboardLimit,
	}
	for raw, want := range cases {
		if got := clampLeaderboardLimit(raw); got != want {
			t.Errorf("clampLeaderboardLimit(%q) = %d, want %d", raw, got, want)
		}
	}
}

func TestValidateLeaderboardDeltasAcceptsValid(t *testing.T) {
	valid := []UpdateLeaderboardRequest{
		{CharacterID: 1, PvPKills: 1},
		{CharacterID: 42, MonsterKills: 3},
		{CharacterID: 7, Deaths: 1},
		{CharacterID: 9, PvPKills: 2, MonsterKills: 5, Deaths: 1},
	}
	for _, req := range valid {
		if err := validateLeaderboardDeltas(req); err != nil {
			t.Errorf("validateLeaderboardDeltas(%+v): unexpected error %v", req, err)
		}
	}
}

func TestValidateLeaderboardDeltasRejectsInvalid(t *testing.T) {
	invalid := []UpdateLeaderboardRequest{
		{CharacterID: 0, PvPKills: 1},  // missing character id
		{CharacterID: -1, PvPKills: 1}, // non-positive character id
		{CharacterID: 1, PvPKills: -1}, // negative delta
		{CharacterID: 1, Deaths: -3},   // negative delta
		{CharacterID: 1},               // all-zero no-op
	}
	for _, req := range invalid {
		if err := validateLeaderboardDeltas(req); err == nil {
			t.Errorf("validateLeaderboardDeltas(%+v): expected error, got nil", req)
		}
	}
}
