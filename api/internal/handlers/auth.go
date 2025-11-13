package handlers

import (
	"database/sql"
	"encoding/json"
	"log"
	"net/http"
	"strings"

	"github.com/omega-realm/api/internal/auth"
	"github.com/omega-realm/api/internal/database"
	"github.com/omega-realm/api/internal/models"
	"golang.org/x/crypto/bcrypt"
)

type AuthHandler struct {
	db *database.DB
}

func NewAuthHandler(db *database.DB) *AuthHandler {
	return &AuthHandler{db: db}
}

// RegisterRequest represents the registration request body
type RegisterRequest struct {
	Username string `json:"username"`
	Email    string `json:"email"`
	Password string `json:"password"`
	Region   string `json:"region"`
}

// LoginRequest represents the login request body
type LoginRequest struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

// RefreshTokenRequest represents the refresh token request body
type RefreshTokenRequest struct {
	RefreshToken string `json:"refresh_token"`
}

// AuthResponse represents the authentication response
type AuthResponse struct {
	AccessToken  string       `json:"access_token"`
	RefreshToken string       `json:"refresh_token"`
	User         *models.User `json:"user"`
}

// ErrorResponse represents an error response
type ErrorResponse struct {
	Error string `json:"error"`
}

// Register handles user registration
func (h *AuthHandler) Register(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req RegisterRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid request body"})
		return
	}

	// Validate input
	if err := validateRegisterRequest(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: err.Error()})
		return
	}

	// Hash password
	hashedPassword, err := bcrypt.GenerateFromPassword([]byte(req.Password), bcrypt.DefaultCost)
	if err != nil {
		log.Printf("[Auth] Failed to hash password: %v", err)
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to create user"})
		return
	}

	// Set default region if not provided
	if req.Region == "" {
		req.Region = "Asia"
	}

	// Insert user into database
	var userID int
	query := `
		INSERT INTO users (username, email, password_hash, region)
		VALUES ($1, $2, $3, $4)
		RETURNING id
	`
	err = h.db.QueryRow(query, req.Username, req.Email, string(hashedPassword), req.Region).Scan(&userID)
	if err != nil {
		if strings.Contains(err.Error(), "duplicate key") {
			w.WriteHeader(http.StatusConflict)
			json.NewEncoder(w).Encode(ErrorResponse{Error: "Username or email already exists"})
			return
		}
		log.Printf("[Auth] Failed to insert user: %v", err)
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to create user"})
		return
	}

	// Generate tokens
	accessToken, err := auth.GenerateAccessToken(userID, req.Username, req.Email, req.Region)
	if err != nil {
		log.Printf("[Auth] Failed to generate access token: %v", err)
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to generate token"})
		return
	}

	refreshToken, err := auth.GenerateRefreshToken(userID, req.Username)
	if err != nil {
		log.Printf("[Auth] Failed to generate refresh token: %v", err)
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to generate token"})
		return
	}

	user := &models.User{
		ID:       userID,
		Username: req.Username,
		Email:    req.Email,
		Region:   req.Region,
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(AuthResponse{
		AccessToken:  accessToken,
		RefreshToken: refreshToken,
		User:         user,
	})

	log.Printf("[Auth] User registered successfully: %s (ID: %d)", req.Username, userID)
}

// Login handles user authentication
func (h *AuthHandler) Login(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req LoginRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid request body"})
		return
	}

	// Validate input
	if req.Username == "" || req.Password == "" {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Username and password are required"})
		return
	}

	// Fetch user from database
	var user models.User
	query := `
		SELECT id, username, email, password_hash, region, created_at
		FROM users
		WHERE username = $1
	`
	err := h.db.QueryRow(query, req.Username).Scan(
		&user.ID,
		&user.Username,
		&user.Email,
		&user.PasswordHash,
		&user.Region,
		&user.CreatedAt,
	)
	if err != nil {
		if err == sql.ErrNoRows {
			w.WriteHeader(http.StatusUnauthorized)
			json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid username or password"})
			return
		}
		log.Printf("[Auth] Failed to fetch user: %v", err)
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Internal server error"})
		return
	}

	// Verify password
	err = bcrypt.CompareHashAndPassword([]byte(user.PasswordHash), []byte(req.Password))
	if err != nil {
		w.WriteHeader(http.StatusUnauthorized)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid username or password"})
		return
	}

	// Generate tokens
	accessToken, err := auth.GenerateAccessToken(user.ID, user.Username, user.Email, user.Region)
	if err != nil {
		log.Printf("[Auth] Failed to generate access token: %v", err)
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to generate token"})
		return
	}

	refreshToken, err := auth.GenerateRefreshToken(user.ID, user.Username)
	if err != nil {
		log.Printf("[Auth] Failed to generate refresh token: %v", err)
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to generate token"})
		return
	}

	// Clear password hash before sending
	user.PasswordHash = ""

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(AuthResponse{
		AccessToken:  accessToken,
		RefreshToken: refreshToken,
		User:         &user,
	})

	log.Printf("[Auth] User logged in successfully: %s (ID: %d)", user.Username, user.ID)
}

// RefreshToken handles token refresh
func (h *AuthHandler) RefreshToken(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req RefreshTokenRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid request body"})
		return
	}

	// Validate refresh token
	claims, err := auth.ValidateRefreshToken(req.RefreshToken)
	if err != nil {
		w.WriteHeader(http.StatusUnauthorized)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid refresh token"})
		return
	}

	// Fetch user from database using subject (username)
	var user models.User
	query := `
		SELECT id, username, email, region
		FROM users
		WHERE username = $1
	`
	err = h.db.QueryRow(query, claims.Subject).Scan(
		&user.ID,
		&user.Username,
		&user.Email,
		&user.Region,
	)
	if err != nil {
		if err == sql.ErrNoRows {
			w.WriteHeader(http.StatusUnauthorized)
			json.NewEncoder(w).Encode(ErrorResponse{Error: "User not found"})
			return
		}
		log.Printf("[Auth] Failed to fetch user: %v", err)
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Internal server error"})
		return
	}

	// Generate new tokens
	accessToken, err := auth.GenerateAccessToken(user.ID, user.Username, user.Email, user.Region)
	if err != nil {
		log.Printf("[Auth] Failed to generate access token: %v", err)
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to generate token"})
		return
	}

	newRefreshToken, err := auth.GenerateRefreshToken(user.ID, user.Username)
	if err != nil {
		log.Printf("[Auth] Failed to generate refresh token: %v", err)
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ErrorResponse{Error: "Failed to generate token"})
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(AuthResponse{
		AccessToken:  accessToken,
		RefreshToken: newRefreshToken,
		User:         &user,
	})

	log.Printf("[Auth] Token refreshed for user: %s (ID: %d)", user.Username, user.ID)
}

// validateRegisterRequest validates the registration request
func validateRegisterRequest(req *RegisterRequest) error {
	if req.Username == "" {
		return &ValidationError{Field: "username", Message: "Username is required"}
	}
	if len(req.Username) < 3 || len(req.Username) > 50 {
		return &ValidationError{Field: "username", Message: "Username must be between 3 and 50 characters"}
	}
	if req.Email == "" {
		return &ValidationError{Field: "email", Message: "Email is required"}
	}
	if !strings.Contains(req.Email, "@") {
		return &ValidationError{Field: "email", Message: "Invalid email format"}
	}
	if req.Password == "" {
		return &ValidationError{Field: "password", Message: "Password is required"}
	}
	if len(req.Password) < 6 {
		return &ValidationError{Field: "password", Message: "Password must be at least 6 characters"}
	}
	if req.Region != "" && !isValidRegion(req.Region) {
		return &ValidationError{Field: "region", Message: "Invalid region. Must be Asia, Europe, or US-West"}
	}
	return nil
}

// isValidRegion checks if the region is valid
func isValidRegion(region string) bool {
	validRegions := []string{"Asia", "Europe", "US-West"}
	for _, r := range validRegions {
		if r == region {
			return true
		}
	}
	return false
}

// ValidationError represents a validation error
type ValidationError struct {
	Field   string
	Message string
}

func (e *ValidationError) Error() string {
	return e.Message
}
