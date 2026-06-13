// Command gen_ticket_key generates an Ed25519 keypair for session-ticket signing (D9)
// and prints the two env values the deploy needs:
//
//	OMEGA_TICKET_PRIVKEY -> /etc/omega-realm/api.env    (SECRET — the Go API signs with this)
//	OMEGA_TICKET_PUBKEY  -> /etc/omega-realm/server.env (the game server verifies with this)
//
// The private value is the 32-byte Ed25519 seed (hex); the API reconstructs the full key
// with ed25519.NewKeyFromSeed. Run from the api/ directory:
//
//	go run ./cmd/gen_ticket_key
//
// Generate a fresh pair per environment and never commit the private seed.
package main

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"os"
)

func main() {
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		fmt.Fprintln(os.Stderr, "failed to generate Ed25519 key:", err)
		os.Exit(1)
	}

	fmt.Println("# Ed25519 session-ticket keypair — treat the private seed like any secret.")
	fmt.Println("#")
	fmt.Println("# 1) api.env (the API signs tickets — KEEP SECRET):")
	fmt.Printf("OMEGA_TICKET_PRIVKEY=%s\n", hex.EncodeToString(priv.Seed()))
	fmt.Println("#")
	fmt.Println("# 2) server.env (the game server verifies — safe to expose):")
	fmt.Printf("OMEGA_TICKET_PUBKEY=%s\n", hex.EncodeToString(pub))
}
