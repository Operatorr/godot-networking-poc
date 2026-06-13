package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/joho/godotenv"
	"github.com/omega-realm/api/internal/auth"
	"github.com/omega-realm/api/internal/database"
	"github.com/omega-realm/api/internal/handlers"
	"github.com/omega-realm/api/internal/middleware"
	redisClient "github.com/omega-realm/api/internal/redis"
)

func main() {
	// Load .env file
	if err := godotenv.Load(); err != nil {
		log.Println("[API] No .env file found or error loading it, using environment variables")
	}

	// Load JWT config (signing secret + token lifetimes) now that .env is loaded. In
	// production this refuses to start on an empty/placeholder JWT_SECRET_KEY rather than
	// silently signing with a guessable default.
	if err := auth.InitConfig(); err != nil {
		log.Fatalf("[API] JWT config error: %v", err)
	}

	// Load configuration from environment
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	// Load database configuration
	dbConfig := database.LoadConfigFromEnv()

	// Initialize database connection
	log.Println("[API] Initializing database connection...")
	db, err := database.NewConnection(dbConfig)
	if err != nil {
		log.Fatalf("[API] Failed to connect to database: %v", err)
	}
	defer db.Close()

	log.Println("[API] Database connected successfully")

	// Initialize database schema
	log.Println("[API] Initializing database schema...")
	if err := db.InitSchema(); err != nil {
		log.Fatalf("[API] Failed to initialize schema: %v", err)
	}

	// Load Redis configuration
	redisConfig := redisClient.LoadConfigFromEnv()

	// Initialize Redis connection
	log.Println("[API] Initializing Redis connection...")
	redis, err := redisClient.NewClient(redisConfig)
	if err != nil {
		log.Fatalf("[API] Failed to connect to Redis: %v", err)
	}
	defer redis.Close()

	log.Println("[API] Redis connected successfully")

	// Session-ticket signer (D9): the API holds the Ed25519 private key and mints
	// short-lived signed tickets; the game server holds only OMEGA_TICKET_PUBKEY and
	// verifies. Unset OMEGA_TICKET_PRIVKEY => signing disabled (clients join unsigned,
	// which requires the server to run with --allow-unsigned-tickets).
	ticketSigner, err := auth.NewTicketSigner(os.Getenv("OMEGA_TICKET_PRIVKEY"), ticketTTL())
	if err != nil {
		log.Fatalf("[API] Invalid OMEGA_TICKET_PRIVKEY: %v", err)
	}
	if ticketSigner != nil {
		// Log the public key so operators can copy it straight into server.env.
		log.Printf("[API] Session-ticket signing ENABLED (ttl %s) — set in server.env: OMEGA_TICKET_PUBKEY=%s",
			ticketSigner.TTL(), ticketSigner.PublicKeyHex())
	} else {
		log.Println("[API] Session-ticket signing DISABLED (OMEGA_TICKET_PRIVKEY unset); clients must join unsigned")
	}

	// Initialize handlers
	authHandler := handlers.NewAuthHandler(db)
	characterHandler := handlers.NewCharacterHandler(db)
	ticketHandler := handlers.NewTicketHandler(db, ticketSigner)
	leaderboardHandler := handlers.NewLeaderboardHandler(db)
	regionHandler := handlers.NewRegionHandler(redis)
	internalHandler := handlers.NewInternalHandler(db)

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

	// Character routes (protected with JWT auth)
	mux.HandleFunc("/api/character/me", middleware.RequireAuth(characterHandler.GetCharacter))
	mux.HandleFunc("/api/character/create", middleware.RequireAuth(characterHandler.CreateCharacter))
	mux.HandleFunc("/api/character/sacrifice", middleware.RequireAuth(characterHandler.SacrificeCharacter))
	mux.HandleFunc("/api/character/ticket", middleware.RequireAuth(ticketHandler.IssueTicket))
	mux.HandleFunc("DELETE /api/character", middleware.RequireAuth(characterHandler.DeleteCharacter))

	// Internal server-only routes (guarded by X-Server-Token, NOT JWT). The Rust
	// authoritative server calls these to read/write progression and settle Glory.
	mux.HandleFunc("GET /api/internal/characters/{id}", internalHandler.GetCharacter)
	mux.HandleFunc("POST /api/internal/characters/{id}/progress", internalHandler.UpdateProgress)
	mux.HandleFunc("POST /api/internal/characters/{id}/death", internalHandler.Death)

	// Leaderboard routes
	mux.HandleFunc("/api/leaderboard", leaderboardHandler.GetLeaderboard)
	mux.HandleFunc("/api/leaderboard/update", leaderboardHandler.UpdateLeaderboard)

	// Region routes
	mux.HandleFunc("/api/regions", regionHandler.GetRegions)
	mux.HandleFunc("/api/regions/heartbeat", regionHandler.UpdateRegionHeartbeat)
	mux.HandleFunc("/api/regions/select", middleware.RequireAuth(regionHandler.SelectRegion))

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

// ticketTTL reads the session-ticket lifetime from OMEGA_TICKET_TTL_SECONDS, defaulting
// to 60s. Tickets have no revocation list — expiry IS the revocation story — so keep this
// short. A non-positive or unparseable value falls back to the default.
func ticketTTL() time.Duration {
	const def = 60 * time.Second
	v := os.Getenv("OMEGA_TICKET_TTL_SECONDS")
	if v == "" {
		return def
	}
	secs, err := strconv.Atoi(v)
	if err != nil || secs <= 0 {
		log.Printf("[API] Ignoring invalid OMEGA_TICKET_TTL_SECONDS=%q; using %s", v, def)
		return def
	}
	return time.Duration(secs) * time.Second
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
