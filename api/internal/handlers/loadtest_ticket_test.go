package handlers

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/omega-realm/api/internal/auth"
)

// A fixed Ed25519 seed (32 bytes of 0x07) so the test is deterministic and DB-free —
// IssueLoadTestTicket only needs a signer, never the database.
func loadTestSigner(t *testing.T) *auth.TicketSigner {
	t.Helper()
	seed := bytes.Repeat([]byte{0x07}, ed25519.SeedSize)
	signer, err := auth.NewTicketSigner(hex.EncodeToString(seed), time.Minute)
	if err != nil || signer == nil {
		t.Fatalf("NewTicketSigner: %v", err)
	}
	return signer
}

func postLoadTestTicket(t *testing.T, h *TicketHandler, token string, body string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, "/api/loadtest/ticket", bytes.NewBufferString(body))
	if token != "" {
		req.Header.Set("X-Loadtest-Token", token)
	}
	rec := httptest.NewRecorder()
	h.IssueLoadTestTicket(rec, req)
	return rec
}

// The happy path: a valid secret + synthetic id yields an 86-byte ticket whose signature
// verifies against the signer's public key, with the requested character_id and region in
// the payload. This is exactly what the Rust server's TicketVerifier checks, so a pass here
// means the load-test swarm's ticket will be admitted.
func TestIssueLoadTestTicketMintsVerifiableTicket(t *testing.T) {
	t.Setenv("LOAD_TEST_TICKET_SECRET", "s3cret")
	signer := loadTestSigner(t)
	h := NewTicketHandler(nil, signer)

	const charID = LoadTestCharacterIDMin + 41
	rec := postLoadTestTicket(t, h, "s3cret", `{"character_id":1000041,"region_id":"asia"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}

	var resp TicketResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if resp.CharacterID != int(charID) {
		t.Fatalf("character_id = %d, want %d", resp.CharacterID, charID)
	}
	blob, err := base64.StdEncoding.DecodeString(resp.Ticket)
	if err != nil {
		t.Fatalf("base64 decode: %v", err)
	}
	if len(blob) != auth.TicketLen {
		t.Fatalf("ticket length = %d, want %d", len(blob), auth.TicketLen)
	}

	// Signature verifies with the public half the game server holds.
	payload, sig := blob[:22], blob[22:]
	pubHex := signer.PublicKeyHex()
	pub, err := hex.DecodeString(pubHex)
	if err != nil {
		t.Fatalf("decode pubkey: %v", err)
	}
	if !ed25519.Verify(ed25519.PublicKey(pub), payload, sig) {
		t.Fatal("minted ticket does not verify against the signer public key")
	}
	// Payload binds the requested character_id (LE u32 at [1:5]) and Asia region (0 at [5]).
	if got := binary.LittleEndian.Uint32(payload[1:5]); got != charID {
		t.Fatalf("payload character_id = %d, want %d", got, charID)
	}
	if payload[5] != 0 {
		t.Fatalf("payload region = %d, want 0 (asia)", payload[5])
	}
}

// Ids below the synthetic floor are refused, so even with the secret nobody can mint a
// ticket that touches a real character row.
func TestIssueLoadTestTicketRejectsRealCharacterRange(t *testing.T) {
	t.Setenv("LOAD_TEST_TICKET_SECRET", "s3cret")
	h := NewTicketHandler(nil, loadTestSigner(t))

	rec := postLoadTestTicket(t, h, "s3cret", `{"character_id":42,"region_id":"asia"}`)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400 (body %s)", rec.Code, rec.Body.String())
	}
}

func TestIssueLoadTestTicketSecretGuard(t *testing.T) {
	signer := loadTestSigner(t)

	t.Run("wrong secret is 401", func(t *testing.T) {
		t.Setenv("LOAD_TEST_TICKET_SECRET", "s3cret")
		h := NewTicketHandler(nil, signer)
		rec := postLoadTestTicket(t, h, "nope", `{"character_id":1000001}`)
		if rec.Code != http.StatusUnauthorized {
			t.Fatalf("status = %d, want 401", rec.Code)
		}
	})

	t.Run("unset secret is 503 (dormant)", func(t *testing.T) {
		t.Setenv("LOAD_TEST_TICKET_SECRET", "")
		h := NewTicketHandler(nil, signer)
		rec := postLoadTestTicket(t, h, "anything", `{"character_id":1000001}`)
		if rec.Code != http.StatusServiceUnavailable {
			t.Fatalf("status = %d, want 503", rec.Code)
		}
	})
}
