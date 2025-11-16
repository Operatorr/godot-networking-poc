package redis

import (
	"context"
	"fmt"
	"log"
	"os"
	"strconv"
	"time"

	"github.com/redis/go-redis/v9"
)

// Client wraps the Redis client
type Client struct {
	*redis.Client
}

// Config holds Redis configuration
type Config struct {
	Host        string
	Port        string
	Password    string
	DB          int
	PoolSize    int
	DialTimeout time.Duration
}

// LoadConfigFromEnv loads Redis configuration from environment variables
func LoadConfigFromEnv() *Config {
	return &Config{
		Host:        getEnv("REDIS_HOST", "localhost"),
		Port:        getEnv("REDIS_PORT", "6379"),
		Password:    getEnv("REDIS_PASSWORD", ""),
		DB:          getEnvAsInt("REDIS_DB", 0),
		PoolSize:    getEnvAsInt("REDIS_POOL_SIZE", 10),
		DialTimeout: getEnvAsDuration("REDIS_DIAL_TIMEOUT", 10*time.Second),
	}
}

// NewClient creates a new Redis client with the provided configuration
func NewClient(config *Config) (*Client, error) {
	addr := fmt.Sprintf("%s:%s", config.Host, config.Port)

	rdb := redis.NewClient(&redis.Options{
		Addr:         addr,
		Password:     config.Password,
		DB:           config.DB,
		PoolSize:     config.PoolSize,
		DialTimeout:  config.DialTimeout,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 30 * time.Second,
		PoolTimeout:  30 * time.Second,
	})

	// Test connection
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := rdb.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("failed to connect to Redis: %w", err)
	}

	log.Printf("[Redis] Connected to %s (DB: %d)", addr, config.DB)
	log.Printf("[Redis] Pool config: PoolSize=%d", config.PoolSize)

	return &Client{rdb}, nil
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
		log.Printf("[Redis] Invalid integer value for %s: %s, using default: %d", key, valueStr, defaultValue)
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
		log.Printf("[Redis] Invalid duration value for %s: %s, using default: %s", key, valueStr, defaultValue)
		return defaultValue
	}
	return value
}
