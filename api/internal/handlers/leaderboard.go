package handlers

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"time"

	"github.com/omega-realm/api/internal/database"
)

type LeaderboardHandler struct {
	db *database.DB
}

func NewLeaderboardHandler(db *database.DB) *LeaderboardHandler {
	return &LeaderboardHandler{db: db}
}

// leaderboardMetrics maps the public ?metric= value to its TRUSTED SQL column name.
// The map IS the allowlist: a metric absent here is rejected, so the column name that
// reaches the ORDER BY clause is always one of these fixed literals and never
// attacker-controlled — there is no SQL-injection surface even though the column is
// interpolated (a column name cannot be a bound parameter).
var leaderboardMetrics = map[string]string{
	"pvp_kills":     "pvp_kills",
	"monster_kills": "monster_kills",
	"deaths":        "deaths",
}

const (
	defaultLeaderboardMetric = "pvp_kills"
	defaultLeaderboardLimit  = 100
	maxLeaderboardLimit      = 100
)

// LeaderboardEntry is one ranked row returned by GetLeaderboard.
type LeaderboardEntry struct {
	Rank          int       `json:"rank"`
	CharacterName string    `json:"character_name"`
	Username      string    `json:"username"`
	Region        string    `json:"region"`
	PvPKills      int       `json:"pvp_kills"`
	MonsterKills  int       `json:"monster_kills"`
	Deaths        int       `json:"deaths"`
	UpdatedAt     time.Time `json:"updated_at"`
}

// LeaderboardResponse is the body returned by GetLeaderboard: the resolved metric the
// rows are sorted by, plus the ranked entries (rank 1 = top of the requested metric).
type LeaderboardResponse struct {
	Metric  string             `json:"metric"`
	Entries []LeaderboardEntry `json:"entries"`
}

// UpdateLeaderboardRequest carries non-negative DELTAS to add to a character's tallies.
// Kills/deaths are events, so the game server reports increments rather than absolute
// totals; the API just adds them. character_id is the characters.id primary key.
type UpdateLeaderboardRequest struct {
	CharacterID  int `json:"character_id"`
	PvPKills     int `json:"pvp_kills"`
	MonsterKills int `json:"monster_kills"`
	Deaths       int `json:"deaths"`
}

// GetLeaderboard returns the top characters ranked by the requested metric.
//
// GET /api/leaderboard?metric=pvp_kills|monster_kills|deaths&limit=100  (public read)
func (h *LeaderboardHandler) GetLeaderboard(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	metric := r.URL.Query().Get("metric")
	column, ok := leaderboardColumn(metric)
	if !ok {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{
			Error: "Invalid metric. Valid metrics: pvp_kills, monster_kills, deaths",
		})
		return
	}
	if metric == "" {
		metric = defaultLeaderboardMetric
	}
	limit := clampLeaderboardLimit(r.URL.Query().Get("limit"))

	// column is from the allowlist above, so this interpolation is safe; limit rides
	// as a bound parameter.
	query := fmt.Sprintf(`
		SELECT c.name, u.username, u.region, l.pvp_kills, l.monster_kills, l.deaths, l.updated_at
		FROM leaderboards l
		JOIN characters c ON l.character_id = c.id
		JOIN users u ON c.user_id = u.id
		ORDER BY l.%s DESC, l.updated_at DESC
		LIMIT $1`, column)

	rows, err := h.db.Query(query, limit)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to fetch leaderboard"})
		return
	}
	defer rows.Close()

	entries := make([]LeaderboardEntry, 0, limit)
	rank := 0
	for rows.Next() {
		rank++
		var e LeaderboardEntry
		if err := rows.Scan(
			&e.CharacterName, &e.Username, &e.Region,
			&e.PvPKills, &e.MonsterKills, &e.Deaths, &e.UpdatedAt,
		); err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to read leaderboard"})
			return
		}
		e.Rank = rank
		entries = append(entries, e)
	}
	if err := rows.Err(); err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to read leaderboard"})
		return
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(LeaderboardResponse{Metric: metric, Entries: entries})
}

// UpdateLeaderboard adds kill/death deltas to a character's leaderboard row. Stats are
// server-authoritative ("the client requests, the server decides"), so this is NOT a
// client/JWT endpoint: it is guarded by the shared X-Server-Token, exactly like
// /api/internal/* (see requireServerToken in internal.go). The CMS website must never
// call this — it only reads GET /api/leaderboard.
//
// POST /api/leaderboard/update  (X-Server-Token)
func (h *LeaderboardHandler) UpdateLeaderboard(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !requireServerToken(w, r) {
		return
	}
	w.Header().Set("Content-Type", "application/json")

	var req UpdateLeaderboardRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid request body"})
		return
	}
	if err := validateLeaderboardDeltas(req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: err.Error()})
		return
	}

	// The leaderboard row is created automatically when the character is inserted
	// (trg_create_leaderboard_entry), so a zero-row update means the character (and
	// thus its row) does not exist → 404.
	res, err := h.db.Exec(`
		UPDATE leaderboards
		SET pvp_kills = pvp_kills + $1,
		    monster_kills = monster_kills + $2,
		    deaths = deaths + $3
		WHERE character_id = $4`,
		req.PvPKills, req.MonsterKills, req.Deaths, req.CharacterID,
	)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to update leaderboard"})
		return
	}
	n, err := res.RowsAffected()
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to update leaderboard"})
		return
	}
	if n == 0 {
		w.WriteHeader(http.StatusNotFound)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "No leaderboard entry for that character"})
		return
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(OKResponse{OK: true})
}

// leaderboardColumn resolves a requested metric to its trusted SQL column. An empty
// metric resolves to the default; an unknown metric returns ok=false (→ 400).
func leaderboardColumn(metric string) (string, bool) {
	if metric == "" {
		return leaderboardMetrics[defaultLeaderboardMetric], true
	}
	column, ok := leaderboardMetrics[metric]
	return column, ok
}

// clampLeaderboardLimit parses the raw ?limit= value, falling back to the default when
// empty or unparseable and clamping the result into [1, maxLeaderboardLimit].
func clampLeaderboardLimit(raw string) int {
	if raw == "" {
		return defaultLeaderboardLimit
	}
	n, err := strconv.Atoi(raw)
	if err != nil || n < 1 {
		return defaultLeaderboardLimit
	}
	if n > maxLeaderboardLimit {
		return maxLeaderboardLimit
	}
	return n
}

// validateLeaderboardDeltas rejects a malformed update: a missing character id, any
// negative delta, or an all-zero no-op.
func validateLeaderboardDeltas(req UpdateLeaderboardRequest) error {
	if req.CharacterID <= 0 {
		return fmt.Errorf("character_id is required")
	}
	if req.PvPKills < 0 || req.MonsterKills < 0 || req.Deaths < 0 {
		return fmt.Errorf("stat deltas must be non-negative")
	}
	if req.PvPKills == 0 && req.MonsterKills == 0 && req.Deaths == 0 {
		return fmt.Errorf("at least one stat delta must be provided")
	}
	return nil
}
