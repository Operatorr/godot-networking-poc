package database

import (
	"database/sql"
	"fmt"
	"log"
	"os"
	"strconv"
	"time"

	_ "github.com/lib/pq" // PostgreSQL driver
)

// DB wraps the database connection
type DB struct {
	*sql.DB
}

// Config holds database configuration
type Config struct {
	Host            string
	Port            string
	User            string
	Password        string
	DBName          string
	SSLMode         string
	MaxOpenConns    int
	MaxIdleConns    int
	ConnMaxLifetime time.Duration
	ConnMaxIdleTime time.Duration
}

// LoadConfigFromEnv loads database configuration from environment variables
func LoadConfigFromEnv() *Config {
	return &Config{
		Host:            getEnv("DB_HOST", "localhost"),
		Port:            getEnv("DB_PORT", "5432"),
		User:            getEnv("DB_USER", "omega"),
		Password:        getEnv("DB_PASSWORD", "omega_password"),
		DBName:          getEnv("DB_NAME", "omega_db"),
		SSLMode:         getEnv("DB_SSLMODE", "disable"),
		MaxOpenConns:    getEnvAsInt("DB_MAX_OPEN_CONNS", 25),
		MaxIdleConns:    getEnvAsInt("DB_MAX_IDLE_CONNS", 5),
		ConnMaxLifetime: getEnvAsDuration("DB_CONN_MAX_LIFETIME", 5*time.Minute),
		ConnMaxIdleTime: getEnvAsDuration("DB_CONN_MAX_IDLE_TIME", 10*time.Minute),
	}
}

// NewConnection creates a new database connection with the provided configuration
func NewConnection(config *Config) (*DB, error) {
	connStr := fmt.Sprintf(
		"host=%s port=%s user=%s password=%s dbname=%s sslmode=%s",
		config.Host, config.Port, config.User, config.Password, config.DBName, config.SSLMode,
	)

	db, err := sql.Open("postgres", connStr)
	if err != nil {
		return nil, fmt.Errorf("failed to open database: %w", err)
	}

	// Configure connection pool
	db.SetMaxOpenConns(config.MaxOpenConns)
	db.SetMaxIdleConns(config.MaxIdleConns)
	db.SetConnMaxLifetime(config.ConnMaxLifetime)
	db.SetConnMaxIdleTime(config.ConnMaxIdleTime)

	// Test connection
	if err := db.Ping(); err != nil {
		return nil, fmt.Errorf("failed to ping database: %w", err)
	}

	log.Printf("[Database] Connected to %s:%s/%s", config.Host, config.Port, config.DBName)
	log.Printf("[Database] Pool config: MaxOpen=%d, MaxIdle=%d", config.MaxOpenConns, config.MaxIdleConns)

	return &DB{db}, nil
}

// Helper functions for environment variables
func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

func getEnvAsInt(key string, defaultValue int) int {
	valueStr := os.Getenv(key)
	if valueStr == "" {
		return defaultValue
	}
	value, err := strconv.Atoi(valueStr)
	if err != nil {
		log.Printf("[Database] Invalid integer value for %s: %s, using default: %d", key, valueStr, defaultValue)
		return defaultValue
	}
	return value
}

func getEnvAsDuration(key string, defaultValue time.Duration) time.Duration {
	valueStr := os.Getenv(key)
	if valueStr == "" {
		return defaultValue
	}
	value, err := time.ParseDuration(valueStr)
	if err != nil {
		log.Printf("[Database] Invalid duration value for %s: %s, using default: %s", key, valueStr, defaultValue)
		return defaultValue
	}
	return value
}

// InitSchema creates database tables if they don't exist
func (db *DB) InitSchema() error {
	schema := `
	-- Users table
	CREATE TABLE IF NOT EXISTS users (
		id SERIAL PRIMARY KEY,
		username VARCHAR(50) UNIQUE NOT NULL,
		email VARCHAR(255) UNIQUE NOT NULL,
		password_hash VARCHAR(255) NOT NULL,
		region VARCHAR(20) DEFAULT 'Asia',
		created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
	);

	-- Characters table (single character per user)
	CREATE TABLE IF NOT EXISTS characters (
		id SERIAL PRIMARY KEY,
		user_id INTEGER UNIQUE REFERENCES users(id) ON DELETE CASCADE,
		name VARCHAR(50) UNIQUE NOT NULL,
		created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
	);

	-- Leaderboards table
	CREATE TABLE IF NOT EXISTS leaderboards (
		id SERIAL PRIMARY KEY,
		character_id INTEGER UNIQUE REFERENCES characters(id) ON DELETE CASCADE,
		pvp_kills INTEGER DEFAULT 0,
		monster_kills INTEGER DEFAULT 0,
		deaths INTEGER DEFAULT 0,
		updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
	);

	-- Sessions table
	CREATE TABLE IF NOT EXISTS sessions (
		id SERIAL PRIMARY KEY,
		character_id INTEGER REFERENCES characters(id) ON DELETE CASCADE,
		server_region VARCHAR(20),
		started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
		ended_at TIMESTAMP
	);

	-- Create indexes for performance
	CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
	CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
	CREATE INDEX IF NOT EXISTS idx_characters_user_id ON characters(user_id);
	CREATE INDEX IF NOT EXISTS idx_characters_name ON characters(name);
	CREATE INDEX IF NOT EXISTS idx_leaderboards_character_id ON leaderboards(character_id);
	CREATE INDEX IF NOT EXISTS idx_leaderboards_pvp_kills ON leaderboards(pvp_kills DESC);
	CREATE INDEX IF NOT EXISTS idx_sessions_character_id ON sessions(character_id);
	CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions(started_at DESC);
	`

	_, err := db.Exec(schema)
	if err != nil {
		return fmt.Errorf("failed to initialize schema: %w", err)
	}

	// Initialize triggers and functions
	if err := db.initTriggers(); err != nil {
		return fmt.Errorf("failed to initialize triggers: %w", err)
	}

	log.Println("[Database] Schema initialized with indexes and triggers")
	return nil
}

// initTriggers creates database triggers for automation
func (db *DB) initTriggers() error {
	triggers := `
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
	`

	_, err := db.Exec(triggers)
	return err
}
