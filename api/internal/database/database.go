package database

import (
	"database/sql"
	"fmt"
	"log"

	_ "github.com/lib/pq" // PostgreSQL driver
)

// DB wraps the database connection
type DB struct {
	*sql.DB
}

// NewConnection creates a new database connection
func NewConnection(host string) (*DB, error) {
	// TODO: Load from environment variables
	connStr := fmt.Sprintf(
		"host=%s port=5432 user=omega password=omega_password dbname=omega_db sslmode=disable",
		host,
	)

	db, err := sql.Open("postgres", connStr)
	if err != nil {
		return nil, fmt.Errorf("failed to open database: %w", err)
	}

	// Test connection
	if err := db.Ping(); err != nil {
		return nil, fmt.Errorf("failed to ping database: %w", err)
	}

	log.Println("[Database] Connection established")

	return &DB{db}, nil
}

// InitSchema creates database tables if they don't exist
func (db *DB) InitSchema() error {
	schema := `
	CREATE TABLE IF NOT EXISTS users (
		id SERIAL PRIMARY KEY,
		username VARCHAR(50) UNIQUE NOT NULL,
		email VARCHAR(255) UNIQUE NOT NULL,
		password_hash VARCHAR(255) NOT NULL,
		region VARCHAR(20) DEFAULT 'Asia',
		created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
	);

	CREATE TABLE IF NOT EXISTS characters (
		id SERIAL PRIMARY KEY,
		user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
		name VARCHAR(50) UNIQUE NOT NULL,
		created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
	);

	CREATE TABLE IF NOT EXISTS leaderboards (
		id SERIAL PRIMARY KEY,
		character_id INTEGER REFERENCES characters(id) ON DELETE CASCADE,
		pvp_kills INTEGER DEFAULT 0,
		monster_kills INTEGER DEFAULT 0,
		deaths INTEGER DEFAULT 0,
		updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
	);

	CREATE TABLE IF NOT EXISTS sessions (
		id SERIAL PRIMARY KEY,
		character_id INTEGER REFERENCES characters(id) ON DELETE CASCADE,
		server_region VARCHAR(20),
		started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
		ended_at TIMESTAMP
	);
	`

	_, err := db.Exec(schema)
	if err != nil {
		return fmt.Errorf("failed to initialize schema: %w", err)
	}

	log.Println("[Database] Schema initialized")
	return nil
}
