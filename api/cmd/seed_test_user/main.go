package main

import (
	"database/sql"
	"flag"
	"fmt"
	"log"
	"os"
	"strings"

	"github.com/joho/godotenv"
	"github.com/omega-realm/api/internal/database"
	"golang.org/x/crypto/bcrypt"
)

const (
	defaultEmailDomain = "example.test"
	defaultRegion      = "Asia"
)

func main() {
	log.SetFlags(0)
	loadEnvFiles()

	username := flag.String("username", envOrDefault("TEST_USERNAME", ""), "username to seed; defaults to TEST_USERNAME")
	password := flag.String("password", envOrDefault("TEST_PASSWORD", ""), "password to seed; defaults to TEST_PASSWORD")
	email := flag.String("email", envOrDefault("TEST_EMAIL", ""), "email to seed; defaults to <username>@example.test")
	region := flag.String("region", defaultSeedRegion(), "user region: Asia, Europe, or US-West")
	resetCharacter := flag.Bool("reset-character", false, "delete this user's existing character so character creation can be tested")
	flag.Parse()

	*username = strings.TrimSpace(*username)
	*email = strings.TrimSpace(*email)
	*region = normalizeRegion(*region)

	if *username == "" {
		log.Fatal("missing username: set TEST_USERNAME in .env.test or pass -username")
	}
	if *password == "" {
		log.Fatal("missing password: set TEST_PASSWORD in .env.test or pass -password")
	}
	if len(*username) < 3 || len(*username) > 50 {
		log.Fatal("username must be between 3 and 50 characters")
	}
	if len(*password) < 6 {
		log.Fatal("password must be at least 6 characters")
	}
	if *email == "" {
		*email = fmt.Sprintf("%s@%s", *username, defaultEmailDomain)
	}
	if !strings.Contains(*email, "@") {
		log.Fatal("email must contain @")
	}
	if !isValidRegion(*region) {
		log.Fatalf("invalid region %q: must be Asia, Europe, or US-West", *region)
	}

	config := database.LoadConfigFromEnv()
	db, err := database.NewConnection(config)
	if err != nil {
		log.Fatalf("failed to connect to database: %v", err)
	}
	defer db.Close()

	if err := db.InitSchema(); err != nil {
		log.Fatalf("failed to initialize schema: %v", err)
	}

	hashedPassword, err := bcrypt.GenerateFromPassword([]byte(*password), bcrypt.DefaultCost)
	if err != nil {
		log.Fatalf("failed to hash password: %v", err)
	}

	var userID int
	err = db.QueryRow(`
		INSERT INTO users (username, email, password_hash, region)
		VALUES ($1, $2, $3, $4)
		ON CONFLICT (username) DO UPDATE SET
			email = EXCLUDED.email,
			password_hash = EXCLUDED.password_hash,
			region = EXCLUDED.region
		RETURNING id
	`, *username, *email, string(hashedPassword), *region).Scan(&userID)
	if err != nil {
		log.Fatalf("failed to upsert user: %v", err)
	}

	if *resetCharacter {
		result, err := db.Exec(`DELETE FROM characters WHERE user_id = $1`, userID)
		if err != nil {
			log.Fatalf("failed to reset character: %v", err)
		}
		deleted, _ := result.RowsAffected()
		if deleted > 0 {
			log.Printf("deleted %d existing character(s) for %s", deleted, *username)
		}
	}

	var characterName string
	characterErr := db.QueryRow(`SELECT name FROM characters WHERE user_id = $1`, userID).Scan(&characterName)

	log.Printf("seeded local login user:")
	log.Printf("  username: %s", *username)
	log.Printf("  password: %s", mask(*password))
	log.Printf("  email:    %s", *email)
	log.Printf("  region:   %s", *region)
	if characterErr == nil {
		log.Printf("  character: %s (preserved; pass -reset-character to delete it)", characterName)
	} else if characterErr == sql.ErrNoRows {
		log.Printf("  character: none; login will route to character creation")
	} else {
		log.Fatalf("failed to check character: %v", characterErr)
	}
}

func loadEnvFiles() {
	paths := []string{".env", "../.env.test", ".env.test"}
	for _, path := range paths {
		if _, err := os.Stat(path); err == nil {
			if err := godotenv.Load(path); err != nil {
				log.Printf("warning: failed to load %s: %v", path, err)
			}
		}
	}
}

func envOrDefault(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func defaultSeedRegion() string {
	for _, key := range []string{"TEST_REGION", "TEST_REALM", "DEFAULT_REGION"} {
		if value := os.Getenv(key); value != "" {
			return normalizeRegion(value)
		}
	}
	return defaultRegion
}

func normalizeRegion(region string) string {
	region = strings.TrimSpace(region)
	if strings.HasPrefix(region, "Asia") {
		return "Asia"
	}
	if strings.HasPrefix(region, "Europe") {
		return "Europe"
	}
	if strings.HasPrefix(region, "US-West") {
		return "US-West"
	}
	return region
}

func isValidRegion(region string) bool {
	switch region {
	case "Asia", "Europe", "US-West":
		return true
	default:
		return false
	}
}

func mask(value string) string {
	if value == "" {
		return ""
	}
	return strings.Repeat("*", len(value))
}
