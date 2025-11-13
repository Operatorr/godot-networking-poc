package middleware

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"

	"github.com/omega-realm/api/internal/auth"
)

// contextKey is a custom type for context keys to avoid collisions
type contextKey string

const (
	// UserContextKey is the key for storing user claims in request context
	UserContextKey contextKey = "user"
)

// ErrorResponse represents an error response
type ErrorResponse struct {
	Error string `json:"error"`
}

// RequireAuth is a middleware that validates JWT tokens
func RequireAuth(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		// Extract token from Authorization header
		authHeader := r.Header.Get("Authorization")
		if authHeader == "" {
			w.WriteHeader(http.StatusUnauthorized)
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(ErrorResponse{Error: "Missing authorization header"})
			return
		}

		// Check if header has Bearer prefix
		parts := strings.Split(authHeader, " ")
		if len(parts) != 2 || parts[0] != "Bearer" {
			w.WriteHeader(http.StatusUnauthorized)
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid authorization header format. Use: Bearer <token>"})
			return
		}

		tokenString := parts[1]

		// Validate token
		claims, err := auth.ValidateToken(tokenString)
		if err != nil {
			w.WriteHeader(http.StatusUnauthorized)
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(ErrorResponse{Error: "Invalid or expired token"})
			return
		}

		// Add claims to request context
		ctx := context.WithValue(r.Context(), UserContextKey, claims)
		r = r.WithContext(ctx)

		// Call next handler
		next.ServeHTTP(w, r)
	}
}

// GetUserClaims extracts user claims from request context
func GetUserClaims(r *http.Request) (*auth.CustomClaims, bool) {
	claims, ok := r.Context().Value(UserContextKey).(*auth.CustomClaims)
	return claims, ok
}
