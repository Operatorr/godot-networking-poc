package auth

import (
	"crypto/ed25519"
	"encoding/hex"
	"testing"
	"time"
)

// Canonical cross-language test vector. The SAME constants are asserted in the Rust
// suite (rust/server/src/auth.rs `go_cross_language_ticket_vector`). Ed25519 (RFC 8032)
// is deterministic, so a given (seed, payload) yields exactly one signature in any
// correct implementation — if Go and Rust both reproduce these bytes, the wire contract
// (payload layout + signing) is provably identical across the two languages.
//
// Vector: seed = 32 × 0x07, character_id = 42, region = 0, issued = 1000 ms, expires = 60000 ms.
const (
	vecPayloadHex   = "012a00000000e80300000000000060ea000000000000"
	vecSignatureHex = "005b771601d53ec91d71fa0bfe6dda2c099821c0bcf2bc15b005e6dce24175157d1325ce41735e56211b6ca493a9b42f238309d9d37371ece1508630c8473c05"
	vecPubKeyHex    = "ea4a6c63e29c520abef5507b132ec5f9954776aebebe7b92421eea691446d22c"
)

func sevenSeedHex() string {
	var seed [ed25519.SeedSize]byte
	for i := range seed {
		seed[i] = 7
	}
	return hex.EncodeToString(seed[:])
}

func TestTicketCrossLanguageVector(t *testing.T) {
	signer, err := NewTicketSigner(sevenSeedHex(), time.Minute)
	if err != nil {
		t.Fatalf("NewTicketSigner: %v", err)
	}

	if got := signer.PublicKeyHex(); got != vecPubKeyHex {
		t.Errorf("pubkey mismatch:\n got %s\nwant %s", got, vecPubKeyHex)
	}

	// Reproduce the exact payload + signature of the canonical vector.
	payload := ticketPayload(42, 0, 1000, 60000)
	if got := hex.EncodeToString(payload); got != vecPayloadHex {
		t.Errorf("payload layout drifted:\n got %s\nwant %s", got, vecPayloadHex)
	}
	sig := ed25519.Sign(signer.key, payload)
	if got := hex.EncodeToString(sig); got != vecSignatureHex {
		t.Errorf("signature drifted:\n got %s\nwant %s", got, vecSignatureHex)
	}
}

func TestMintLayoutAndSelfVerify(t *testing.T) {
	signer, err := NewTicketSigner(sevenSeedHex(), 90*time.Second)
	if err != nil {
		t.Fatalf("NewTicketSigner: %v", err)
	}

	issued := time.UnixMilli(1_700_000_000_000)
	blob, expires := signer.MintAt(1234, regionEurope, issued)

	if len(blob) != TicketLen {
		t.Fatalf("ticket length = %d, want %d", len(blob), TicketLen)
	}
	if expires != uint64(issued.Add(90*time.Second).UnixMilli()) {
		t.Errorf("expires = %d, want issued + ttl", expires)
	}

	// The 64-byte signature must verify against the payload with the public key —
	// this is exactly what the Rust server's verify_strict does.
	payload := blob[:ticketPayloadLen]
	sig := blob[ticketPayloadLen:]
	pub := signer.key.Public().(ed25519.PublicKey)
	if !ed25519.Verify(pub, payload, sig) {
		t.Error("minted ticket failed self-verification")
	}

	// Spot-check the payload fields decode back to what we minted.
	if payload[0] != TicketVersion {
		t.Errorf("version byte = %d, want %d", payload[0], TicketVersion)
	}
	if payload[5] != regionEurope {
		t.Errorf("region byte = %d, want %d", payload[5], regionEurope)
	}
}

func TestRegionToWire(t *testing.T) {
	cases := map[string]uint8{
		"asia": 0, "Asia": 0, "local": 0, "": 0, "mars": 0,
		"europe": 1, "Europe": 1,
		"us-west": 2, "US-West": 2, "us_west": 2,
		"us-east": 3, "us_east": 3,
	}
	for in, want := range cases {
		if got := RegionToWire(in); got != want {
			t.Errorf("RegionToWire(%q) = %d, want %d", in, got, want)
		}
	}
}

func TestNewTicketSignerRejectsBadKeys(t *testing.T) {
	if s, err := NewTicketSigner("", time.Minute); s != nil || err != nil {
		t.Errorf("empty seed: want (nil, nil), got (%v, %v)", s, err)
	}
	if _, err := NewTicketSigner("not-hex", time.Minute); err == nil {
		t.Error("non-hex seed should error")
	}
	if _, err := NewTicketSigner("abcd", time.Minute); err == nil {
		t.Error("short seed should error")
	}
}
