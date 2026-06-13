package auth

import (
	"testing"
	"time"
)

// TestInitConfigSourcesSecretFromJWTSecretKey is the regression guard for the auth-bypass
// bug: the code once read JWT_SECRET while every env file/doc set JWT_SECRET_KEY, so the
// configured secret was ignored and a public hardcoded default signed every token. The
// secret MUST come from JWT_SECRET_KEY.
func TestInitConfigSourcesSecretFromJWTSecretKey(t *testing.T) {
	const want = "a-strong-secret-value"
	t.Setenv("ENVIRONMENT", "development")
	t.Setenv("JWT_SECRET_KEY", want)
	// The old (wrong) name must have no effect.
	t.Setenv("JWT_SECRET", "this-must-be-ignored")

	if err := InitConfig(); err != nil {
		t.Fatalf("InitConfig: %v", err)
	}
	if got := string(jwtSecret); got != want {
		t.Fatalf("jwtSecret = %q, want it sourced from JWT_SECRET_KEY (%q)", got, want)
	}

	// A token issued with the configured secret must validate end-to-end.
	tok, err := GenerateAccessToken(7, "alice", "alice@example.com", "Asia")
	if err != nil {
		t.Fatalf("GenerateAccessToken: %v", err)
	}
	claims, err := ValidateToken(tok)
	if err != nil {
		t.Fatalf("ValidateToken: %v", err)
	}
	if claims.UserID != 7 || claims.Username != "alice" {
		t.Fatalf("round-trip claims = %+v, want UserID=7 Username=alice", claims)
	}
}

// TestInitConfigProductionRejectsWeakSecret asserts the fail-fast: in production an empty
// or placeholder JWT_SECRET_KEY must be a startup error, never an insecure default.
func TestInitConfigProductionRejectsWeakSecret(t *testing.T) {
	cases := []struct {
		name   string
		secret string // empty string means JWT_SECRET_KEY unset
	}{
		{"unset", ""},
		{"deploy placeholder", "CHANGE_ME_TO_A_SECURE_SECRET"},
		{"dev env placeholder", "your-secret-key-change-this-in-production"},
		{"former hardcoded default", "your-secret-key-change-in-production"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			t.Setenv("ENVIRONMENT", "production")
			t.Setenv("JWT_SECRET_KEY", tc.secret)
			if err := InitConfig(); err == nil {
				t.Fatalf("InitConfig with %q secret in production: want error, got nil", tc.secret)
			}
		})
	}
}

// TestInitConfigProductionAcceptsStrongSecret confirms a real secret starts cleanly.
func TestInitConfigProductionAcceptsStrongSecret(t *testing.T) {
	const want = "f3a1c9b7e2d4f6a8c0b1d2e3f4a5b6c7"
	t.Setenv("ENVIRONMENT", "production")
	t.Setenv("JWT_SECRET_KEY", want)

	if err := InitConfig(); err != nil {
		t.Fatalf("InitConfig with strong secret in production: %v", err)
	}
	if got := string(jwtSecret); got != want {
		t.Fatalf("jwtSecret = %q, want %q", got, want)
	}
}

// TestInitConfigNonProductionFallsBackToDevSecret asserts local dev keeps working without
// a configured secret (warning, not fatal) and never uses a placeholder verbatim.
func TestInitConfigNonProductionFallsBackToDevSecret(t *testing.T) {
	t.Setenv("ENVIRONMENT", "development")
	t.Setenv("JWT_SECRET_KEY", "")

	if err := InitConfig(); err != nil {
		t.Fatalf("InitConfig in dev with empty secret: want no error, got %v", err)
	}
	if got := string(jwtSecret); got != devInsecureSecret {
		t.Fatalf("jwtSecret = %q, want dev fallback %q", got, devInsecureSecret)
	}
}

// TestInitConfigTokenDurations reconciles the JWT_*_EXPIRY env vars (previously ignored)
// with the durations the code actually uses, including the "d"/"w" day/week suffixes.
func TestInitConfigTokenDurations(t *testing.T) {
	t.Run("env values applied", func(t *testing.T) {
		t.Setenv("ENVIRONMENT", "development")
		t.Setenv("JWT_SECRET_KEY", "secret")
		t.Setenv("JWT_ACCESS_TOKEN_EXPIRY", "15m")
		t.Setenv("JWT_REFRESH_TOKEN_EXPIRY", "7d")

		if err := InitConfig(); err != nil {
			t.Fatalf("InitConfig: %v", err)
		}
		if AccessTokenDuration != 15*time.Minute {
			t.Errorf("AccessTokenDuration = %s, want 15m", AccessTokenDuration)
		}
		if RefreshTokenDuration != 7*24*time.Hour {
			t.Errorf("RefreshTokenDuration = %s, want 168h", RefreshTokenDuration)
		}
	})

	t.Run("unset and invalid fall back to defaults", func(t *testing.T) {
		t.Setenv("ENVIRONMENT", "development")
		t.Setenv("JWT_SECRET_KEY", "secret")
		t.Setenv("JWT_ACCESS_TOKEN_EXPIRY", "")         // unset -> default
		t.Setenv("JWT_REFRESH_TOKEN_EXPIRY", "garbage") // invalid -> default

		if err := InitConfig(); err != nil {
			t.Fatalf("InitConfig: %v", err)
		}
		if AccessTokenDuration != defaultAccessTokenDuration {
			t.Errorf("AccessTokenDuration = %s, want default %s", AccessTokenDuration, defaultAccessTokenDuration)
		}
		if RefreshTokenDuration != defaultRefreshTokenDuration {
			t.Errorf("RefreshTokenDuration = %s, want default %s", RefreshTokenDuration, defaultRefreshTokenDuration)
		}
	})
}

func TestParseExtendedDuration(t *testing.T) {
	cases := []struct {
		in   string
		want time.Duration
		ok   bool
	}{
		{"15m", 15 * time.Minute, true},
		{"1h", time.Hour, true},
		{"7d", 7 * 24 * time.Hour, true},
		{"2w", 2 * 7 * 24 * time.Hour, true},
		{"0d", 0, false},  // non-positive rejected
		{"-5m", 0, false}, // non-positive rejected
		{"garbage", 0, false},
		{"d", 0, false}, // no number
		{"", 0, false},
	}
	for _, tc := range cases {
		got, ok := parseExtendedDuration(tc.in)
		if ok != tc.ok || (ok && got != tc.want) {
			t.Errorf("parseExtendedDuration(%q) = (%s, %v), want (%s, %v)", tc.in, got, ok, tc.want, tc.ok)
		}
	}
}
