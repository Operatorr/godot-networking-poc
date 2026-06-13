package auth

import (
	"errors"
	"fmt"
	"log"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// Default token lifetimes, used when JWT_ACCESS_TOKEN_EXPIRY / JWT_REFRESH_TOKEN_EXPIRY
// are unset or unparseable.
const (
	defaultAccessTokenDuration  = 24 * time.Hour     // Access token valid for 24 hours
	defaultRefreshTokenDuration = 7 * 24 * time.Hour // Refresh token valid for 7 days

	// devInsecureSecret is the placeholder secret used outside production when none is
	// configured. It is intentionally NOT a guessable real-looking value; production
	// refuses to start with it (see InitConfig).
	devInsecureSecret = "dev-insecure-secret-do-not-use-in-production"
)

// placeholderSecrets are values that must never sign real tokens: the env templates ship
// with them, and the old hardcoded fallback was public in source. In production, any of
// these (or an empty secret) is fatal — otherwise anyone could forge tokens.
var placeholderSecrets = map[string]struct{}{
	"CHANGE_ME_TO_A_SECURE_SECRET":              {}, // deployment/env/api.env.example
	"your-secret-key-change-this-in-production": {}, // api/.env.example, api/.env
	"your-secret-key-change-in-production":      {}, // former hardcoded default in this file
}

var (
	// jwtSecret signs and validates every access/refresh token. InitConfig loads it from
	// JWT_SECRET_KEY at startup. Until then it holds the dev-insecure default so unit
	// tests can round-trip tokens without environment setup.
	jwtSecret = []byte(devInsecureSecret)

	// Token expiration times. InitConfig overrides these from the environment.
	AccessTokenDuration  = defaultAccessTokenDuration
	RefreshTokenDuration = defaultRefreshTokenDuration
)

// InitConfig loads JWT settings from the environment. It MUST be called once at startup,
// AFTER any .env file is loaded (godotenv.Load) and before tokens are issued or validated.
//
// The signing secret is read from JWT_SECRET_KEY. In production (ENVIRONMENT=production)
// an empty or placeholder secret is fatal: the process refuses to start rather than fall
// back to a guessable default, which would let anyone forge access/refresh tokens and
// impersonate any user. Outside production a missing/placeholder secret logs a warning and
// uses an insecure dev default so local runs work.
//
// Token lifetimes come from JWT_ACCESS_TOKEN_EXPIRY / JWT_REFRESH_TOKEN_EXPIRY. They
// accept Go durations (e.g. "15m", "1h") plus a trailing "d" (days) or "w" (weeks) so the
// documented "7d" form works. Unset or invalid values fall back to the defaults.
func InitConfig() error {
	secret := strings.TrimSpace(os.Getenv("JWT_SECRET_KEY"))
	production := strings.EqualFold(strings.TrimSpace(os.Getenv("ENVIRONMENT")), "production")

	if _, isPlaceholder := placeholderSecrets[secret]; secret == "" || isPlaceholder {
		if production {
			return fmt.Errorf("JWT_SECRET_KEY is unset or still a placeholder; refusing to start in production " +
				"(set a strong secret, e.g. `openssl rand -hex 32`)")
		}
		log.Println("[API] WARNING: JWT_SECRET_KEY unset or placeholder; using an INSECURE dev default. " +
			"Never run production this way.")
		jwtSecret = []byte(devInsecureSecret)
	} else {
		jwtSecret = []byte(secret)
	}

	AccessTokenDuration = parseTokenDuration("JWT_ACCESS_TOKEN_EXPIRY", defaultAccessTokenDuration)
	RefreshTokenDuration = parseTokenDuration("JWT_REFRESH_TOKEN_EXPIRY", defaultRefreshTokenDuration)
	return nil
}

// parseTokenDuration reads a duration env var, falling back to def when unset or invalid.
func parseTokenDuration(key string, def time.Duration) time.Duration {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return def
	}
	if d, ok := parseExtendedDuration(v); ok {
		return d
	}
	log.Printf("[API] Ignoring invalid %s=%q; using %s", key, v, def)
	return def
}

// parseExtendedDuration parses a Go duration string, additionally accepting a trailing
// "d" (days) or "w" (weeks) which time.ParseDuration does not understand. It rejects
// non-positive results. Returns (0, false) on any parse failure.
func parseExtendedDuration(v string) (time.Duration, bool) {
	if n := len(v); n >= 2 && (v[n-1] == 'd' || v[n-1] == 'w') {
		num, err := strconv.ParseFloat(v[:n-1], 64)
		if err != nil {
			return 0, false
		}
		hours := num * 24
		if v[n-1] == 'w' {
			hours *= 7
		}
		d := time.Duration(hours * float64(time.Hour))
		if d <= 0 {
			return 0, false
		}
		return d, true
	}
	d, err := time.ParseDuration(v)
	if err != nil || d <= 0 {
		return 0, false
	}
	return d, true
}

// CustomClaims represents the JWT claims structure
type CustomClaims struct {
	UserID   int    `json:"user_id"`
	Username string `json:"username"`
	Email    string `json:"email"`
	Region   string `json:"region"`
	jwt.RegisteredClaims
}

// GenerateAccessToken creates a new access token for a user
func GenerateAccessToken(userID int, username, email, region string) (string, error) {
	claims := CustomClaims{
		UserID:   userID,
		Username: username,
		Email:    email,
		Region:   region,
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(AccessTokenDuration)),
			IssuedAt:  jwt.NewNumericDate(time.Now()),
			NotBefore: jwt.NewNumericDate(time.Now()),
			Issuer:    "omega-realm-api",
			Subject:   username,
		},
	}

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	tokenString, err := token.SignedString(jwtSecret)
	if err != nil {
		return "", err
	}

	return tokenString, nil
}

// GenerateRefreshToken creates a new refresh token for a user
func GenerateRefreshToken(userID int, username string) (string, error) {
	claims := jwt.RegisteredClaims{
		ExpiresAt: jwt.NewNumericDate(time.Now().Add(RefreshTokenDuration)),
		IssuedAt:  jwt.NewNumericDate(time.Now()),
		NotBefore: jwt.NewNumericDate(time.Now()),
		Issuer:    "omega-realm-api",
		Subject:   username,
		ID:        string(rune(userID)), // Store user ID in JTI claim
	}

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	tokenString, err := token.SignedString(jwtSecret)
	if err != nil {
		return "", err
	}

	return tokenString, nil
}

// ValidateToken validates a JWT token and returns the claims
func ValidateToken(tokenString string) (*CustomClaims, error) {
	token, err := jwt.ParseWithClaims(tokenString, &CustomClaims{}, func(token *jwt.Token) (interface{}, error) {
		// Validate the signing method
		if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errors.New("unexpected signing method")
		}
		return jwtSecret, nil
	})

	if err != nil {
		return nil, err
	}

	if claims, ok := token.Claims.(*CustomClaims); ok && token.Valid {
		return claims, nil
	}

	return nil, errors.New("invalid token")
}

// ValidateRefreshToken validates a refresh token and returns basic claims
func ValidateRefreshToken(tokenString string) (*jwt.RegisteredClaims, error) {
	token, err := jwt.ParseWithClaims(tokenString, &jwt.RegisteredClaims{}, func(token *jwt.Token) (interface{}, error) {
		// Validate the signing method
		if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errors.New("unexpected signing method")
		}
		return jwtSecret, nil
	})

	if err != nil {
		return nil, err
	}

	if claims, ok := token.Claims.(*jwt.RegisteredClaims); ok && token.Valid {
		return claims, nil
	}

	return nil, errors.New("invalid refresh token")
}
