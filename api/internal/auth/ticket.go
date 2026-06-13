package auth

import (
	"crypto/ed25519"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"strings"
	"time"
)

// Session-ticket wire format (D9). This MUST stay byte-for-byte identical to the Rust
// side or every signed join fails verification:
//   - payload layout: rust/protocol/src/client.rs  Ticket::payload_bytes
//   - verification:    rust/server/src/auth.rs       TicketVerifier::verify (Ed25519 verify_strict)
//
// Payload (22 bytes, little-endian):
//
//	[u8 version][u32 character_id][u8 region][u64 issued_at_unix_ms][u64 expires_at_unix_ms]
//
// Full ticket: payload (22) || Ed25519 signature (64) = 86 bytes.
const (
	TicketVersion      = 1
	ticketPayloadLen   = 22
	ticketSignatureLen = ed25519.SignatureSize                 // 64
	TicketLen          = ticketPayloadLen + ticketSignatureLen // 86
)

// Region wire ids — must match protocol::types::region (rust/protocol/src/types.rs).
const (
	regionAsia   uint8 = 0
	regionEurope uint8 = 1
	regionUSWest uint8 = 2
	regionUSEast uint8 = 3
)

// RegionToWire maps an API region id to the u8 the game server expects. It mirrors
// rust/server/src/auth.rs `region_from_string` EXACTLY: lowercase, and anything that
// isn't europe/us-west/us-east (including "asia", "local", and unknown values) maps to
// Asia. If the two ever diverge, signed joins fail with WRONG_REGION.
func RegionToWire(name string) uint8 {
	switch strings.ToLower(strings.TrimSpace(name)) {
	case "europe":
		return regionEurope
	case "us-west", "us_west":
		return regionUSWest
	case "us-east", "us_east":
		return regionUSEast
	default: // "asia", "local", and anything unknown
		return regionAsia
	}
}

// TicketSigner mints short-lived Ed25519 session tickets. The API holds the private
// key; the game server holds only the public half (OMEGA_TICKET_PUBKEY) and can verify
// but never forge. There is NO revocation list — expiry IS the revocation story, so keep
// the TTL short (minutes at most).
type TicketSigner struct {
	key ed25519.PrivateKey
	ttl time.Duration
}

// NewTicketSigner builds a signer from a hex-encoded 32-byte Ed25519 seed
// (OMEGA_TICKET_PRIVKEY). When the seed is empty it returns (nil, nil) so the caller can
// run in unsigned/dev mode without a key — callers must treat a nil *TicketSigner as
// "signing disabled". ttl <= 0 falls back to 60s.
func NewTicketSigner(seedHex string, ttl time.Duration) (*TicketSigner, error) {
	seedHex = strings.TrimSpace(seedHex)
	if seedHex == "" {
		return nil, nil
	}
	seed, err := hex.DecodeString(seedHex)
	if err != nil {
		return nil, fmt.Errorf("OMEGA_TICKET_PRIVKEY is not valid hex: %w", err)
	}
	if len(seed) != ed25519.SeedSize {
		return nil, fmt.Errorf(
			"OMEGA_TICKET_PRIVKEY must be %d bytes (%d hex chars), got %d",
			ed25519.SeedSize, ed25519.SeedSize*2, len(seed))
	}
	if ttl <= 0 {
		ttl = 60 * time.Second
	}
	return &TicketSigner{key: ed25519.NewKeyFromSeed(seed), ttl: ttl}, nil
}

// PublicKeyHex returns the hex-encoded 32-byte public key — exactly the value the game
// server expects in OMEGA_TICKET_PUBKEY.
func (s *TicketSigner) PublicKeyHex() string {
	pub := s.key.Public().(ed25519.PublicKey)
	return hex.EncodeToString(pub)
}

// TTL reports the configured ticket lifetime.
func (s *TicketSigner) TTL() time.Duration { return s.ttl }

// ticketPayload encodes the 22-byte signed payload.
func ticketPayload(characterID uint32, region uint8, issuedAtMs, expiresAtMs uint64) []byte {
	p := make([]byte, ticketPayloadLen)
	p[0] = TicketVersion
	binary.LittleEndian.PutUint32(p[1:5], characterID)
	p[5] = region
	binary.LittleEndian.PutUint64(p[6:14], issuedAtMs)
	binary.LittleEndian.PutUint64(p[14:22], expiresAtMs)
	return p
}

// MintAt builds and signs a ticket for the given character + region using a fixed issue
// time. It is the deterministic core of Mint, separated out so tests can pin the clock.
// expiresAt = issuedAt + ttl. Returns the 86-byte blob and the expiry (unix ms).
func (s *TicketSigner) MintAt(characterID uint32, region uint8, issuedAt time.Time) (blob []byte, expiresAtMs uint64) {
	issuedMs := uint64(issuedAt.UnixMilli())
	expiresMs := uint64(issuedAt.Add(s.ttl).UnixMilli())
	payload := ticketPayload(characterID, region, issuedMs, expiresMs)
	sig := ed25519.Sign(s.key, payload)
	blob = make([]byte, 0, TicketLen)
	blob = append(blob, payload...)
	blob = append(blob, sig...)
	return blob, expiresMs
}

// Mint builds and signs a ticket valid from now for the configured TTL.
func (s *TicketSigner) Mint(characterID uint32, region uint8) (blob []byte, expiresAtMs uint64) {
	return s.MintAt(characterID, region, time.Now())
}
