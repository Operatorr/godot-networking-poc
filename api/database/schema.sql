-- ============================================================================
-- Omega Realm Database Schema
-- ============================================================================
-- PostgreSQL schema for the multiplayer game backend
-- Version: 1.0
-- Date: 2025-11-14
-- ============================================================================

-- ============================================================================
-- TABLES
-- ============================================================================

-- Users table - Stores player account information
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    region VARCHAR(20) DEFAULT 'Asia' CHECK (region IN ('Asia', 'Europe', 'US-West')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT username_length CHECK (char_length(username) >= 3 AND char_length(username) <= 50),
    CONSTRAINT email_format CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
);

COMMENT ON TABLE users IS 'Player account information and authentication data';
COMMENT ON COLUMN users.region IS 'Preferred game server region: Asia, Europe, or US-West';

-- Characters table - Single character slot per player
CREATE TABLE IF NOT EXISTS characters (
    id SERIAL PRIMARY KEY,
    user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(50) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT character_name_length CHECK (char_length(name) >= 3 AND char_length(name) <= 50)
);

COMMENT ON TABLE characters IS 'Player characters - limited to one character per user';
COMMENT ON COLUMN characters.user_id IS 'UNIQUE constraint enforces single character per user';

-- Leaderboards table - PvP and monster kill statistics
CREATE TABLE IF NOT EXISTS leaderboards (
    id SERIAL PRIMARY KEY,
    character_id INTEGER UNIQUE NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    pvp_kills INTEGER DEFAULT 0 CHECK (pvp_kills >= 0),
    monster_kills INTEGER DEFAULT 0 CHECK (monster_kills >= 0),
    deaths INTEGER DEFAULT 0 CHECK (deaths >= 0),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT positive_stats CHECK (pvp_kills >= 0 AND monster_kills >= 0 AND deaths >= 0)
);

COMMENT ON TABLE leaderboards IS 'Player statistics for leaderboard rankings';
COMMENT ON COLUMN leaderboards.pvp_kills IS 'Number of player kills for PvP leaderboard';

-- Sessions table - Track active and historical game sessions
CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    server_region VARCHAR(20) NOT NULL CHECK (server_region IN ('Asia', 'Europe', 'US-West')),
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,

    CONSTRAINT valid_session_time CHECK (ended_at IS NULL OR ended_at >= started_at)
);

COMMENT ON TABLE sessions IS 'Game session tracking for analytics and connection management';
COMMENT ON COLUMN sessions.ended_at IS 'NULL indicates active session';

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Users indexes
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_region ON users(region);
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at DESC);

-- Characters indexes
CREATE INDEX IF NOT EXISTS idx_characters_user_id ON characters(user_id);
CREATE INDEX IF NOT EXISTS idx_characters_name ON characters(name);
CREATE INDEX IF NOT EXISTS idx_characters_created_at ON characters(created_at DESC);

-- Leaderboards indexes
CREATE INDEX IF NOT EXISTS idx_leaderboards_character_id ON leaderboards(character_id);
CREATE INDEX IF NOT EXISTS idx_leaderboards_pvp_kills ON leaderboards(pvp_kills DESC);
CREATE INDEX IF NOT EXISTS idx_leaderboards_monster_kills ON leaderboards(monster_kills DESC);
CREATE INDEX IF NOT EXISTS idx_leaderboards_updated_at ON leaderboards(updated_at DESC);

-- Sessions indexes
CREATE INDEX IF NOT EXISTS idx_sessions_character_id ON sessions(character_id);
CREATE INDEX IF NOT EXISTS idx_sessions_server_region ON sessions(server_region);
CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(character_id, ended_at) WHERE ended_at IS NULL;

-- ============================================================================
-- TRIGGERS
-- ============================================================================

-- Function to update leaderboard timestamp
CREATE OR REPLACE FUNCTION update_leaderboard_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update leaderboard timestamp
DROP TRIGGER IF EXISTS trg_update_leaderboard_timestamp ON leaderboards;
CREATE TRIGGER trg_update_leaderboard_timestamp
    BEFORE UPDATE ON leaderboards
    FOR EACH ROW
    EXECUTE FUNCTION update_leaderboard_timestamp();

-- Function to create leaderboard entry for new characters
CREATE OR REPLACE FUNCTION create_leaderboard_entry()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO leaderboards (character_id, pvp_kills, monster_kills, deaths)
    VALUES (NEW.id, 0, 0, 0);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-create leaderboard entry
DROP TRIGGER IF EXISTS trg_create_leaderboard_entry ON characters;
CREATE TRIGGER trg_create_leaderboard_entry
    AFTER INSERT ON characters
    FOR EACH ROW
    EXECUTE FUNCTION create_leaderboard_entry();

-- ============================================================================
-- VIEWS
-- ============================================================================

-- View for top PvP players
CREATE OR REPLACE VIEW v_pvp_leaderboard AS
SELECT
    c.name AS character_name,
    u.username,
    u.region,
    l.pvp_kills,
    l.deaths,
    CASE
        WHEN l.deaths > 0 THEN ROUND(l.pvp_kills::NUMERIC / l.deaths::NUMERIC, 2)
        ELSE l.pvp_kills::NUMERIC
    END AS kd_ratio,
    l.updated_at
FROM leaderboards l
JOIN characters c ON l.character_id = c.id
JOIN users u ON c.user_id = u.id
ORDER BY l.pvp_kills DESC, l.updated_at DESC
LIMIT 100;

COMMENT ON VIEW v_pvp_leaderboard IS 'Top 100 PvP players with K/D ratio';

-- View for active sessions
CREATE OR REPLACE VIEW v_active_sessions AS
SELECT
    s.id AS session_id,
    c.name AS character_name,
    u.username,
    s.server_region,
    s.started_at,
    EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - s.started_at)) / 60 AS duration_minutes
FROM sessions s
JOIN characters c ON s.character_id = c.id
JOIN users u ON c.user_id = u.id
WHERE s.ended_at IS NULL
ORDER BY s.started_at DESC;

COMMENT ON VIEW v_active_sessions IS 'Currently active game sessions';

-- ============================================================================
-- SAMPLE QUERIES
-- ============================================================================

-- Get top 10 PvP players
-- SELECT * FROM v_pvp_leaderboard LIMIT 10;

-- Get user's character and stats
-- SELECT c.*, l.pvp_kills, l.monster_kills, l.deaths
-- FROM characters c
-- LEFT JOIN leaderboards l ON c.id = l.character_id
-- WHERE c.user_id = $1;

-- Get active sessions by region
-- SELECT * FROM v_active_sessions WHERE server_region = 'Asia';

-- Update player kills (after a kill event)
-- UPDATE leaderboards
-- SET pvp_kills = pvp_kills + 1
-- WHERE character_id = $1;

-- End a session
-- UPDATE sessions
-- SET ended_at = CURRENT_TIMESTAMP
-- WHERE id = $1 AND ended_at IS NULL;

-- ============================================================================
-- DATABASE STATISTICS
-- ============================================================================

-- View table sizes
-- SELECT
--     schemaname,
--     tablename,
--     pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
-- FROM pg_tables
-- WHERE schemaname = 'public'
-- ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
