package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/omega-realm/api/internal/database"
	"github.com/omega-realm/api/internal/handlers"
)

func main() {
	// Load configuration from environment
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	dbHost := os.Getenv("DB_HOST")
	if dbHost == "" {
		dbHost = "localhost"
	}

	// Initialize database connection
	log.Println("[API] Initializing database connection...")
	db, err := database.NewConnection(dbHost)
	if err != nil {
		log.Fatalf("[API] Failed to connect to database: %v", err)
	}
	defer db.Close()

	log.Println("[API] Database connected successfully")

	// Initialize handlers
	authHandler := handlers.NewAuthHandler(db)
	characterHandler := handlers.NewCharacterHandler(db)
	leaderboardHandler := handlers.NewLeaderboardHandler(db)

	// Setup HTTP routes
	mux := http.NewServeMux()

	// Health check
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{
			"status": "healthy",
			"time":   time.Now().Format(time.RFC3339),
		})
	})

	// Auth routes
	mux.HandleFunc("/api/auth/register", authHandler.Register)
	mux.HandleFunc("/api/auth/login", authHandler.Login)
	mux.HandleFunc("/api/auth/refresh", authHandler.RefreshToken)

	// Character routes
	mux.HandleFunc("/api/characters", characterHandler.GetCharacters)
	mux.HandleFunc("/api/characters/create", characterHandler.CreateCharacter)

	// Leaderboard routes
	mux.HandleFunc("/api/leaderboard", leaderboardHandler.GetLeaderboard)
	mux.HandleFunc("/api/leaderboard/update", leaderboardHandler.UpdateLeaderboard)

	// CORS middleware
	handler := corsMiddleware(mux)

	// Start server
	log.Printf("[API] Starting server on port %s...", port)
	server := &http.Server{
		Addr:         ":" + port,
		Handler:      handler,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 15 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	if err := server.ListenAndServe(); err != nil {
		log.Fatalf("[API] Server failed: %v", err)
	}
}

// corsMiddleware adds CORS headers to all responses
func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")

		if r.Method == "OPTIONS" {
			w.WriteHeader(http.StatusOK)
			return
		}

		next.ServeHTTP(w, r)
	})
}
