//! D9 auth: locally-verified Ed25519 session tickets. The Go API signs with the private key;
//! this server holds only the public key — it can verify but cannot forge. No API round-trip on
//! the join hot path; expiry IS the revocation story.

use ed25519_dalek::{Signature, VerifyingKey};
use protocol::types::auth_result_code;
use protocol::Ticket;

pub struct TicketVerifier {
    key: Option<VerifyingKey>,
    pub allow_unsigned: bool,
    /// This Instance's region id (`protocol::types::region` value); ticket must match.
    pub region: u8,
}

impl TicketVerifier {
    pub fn new(pubkey_hex: &str, allow_unsigned: bool, region: u8) -> Result<Self, String> {
        let key = if pubkey_hex.is_empty() {
            None
        } else {
            let bytes = decode_hex(pubkey_hex).ok_or("OMEGA_TICKET_PUBKEY is not valid hex")?;
            let arr: [u8; 32] = bytes
                .try_into()
                .map_err(|_| "OMEGA_TICKET_PUBKEY must be 32 bytes")?;
            Some(VerifyingKey::from_bytes(&arr).map_err(|e| format!("bad Ed25519 key: {e}"))?)
        };
        Ok(Self {
            key,
            allow_unsigned,
            region,
        })
    }

    /// Returns an `auth_result_code` value. `OK` admits the join.
    pub fn verify(&self, ticket: Option<&Ticket>, now_unix_ms: u64) -> u8 {
        let Some(ticket) = ticket else {
            return if self.allow_unsigned {
                auth_result_code::OK
            } else {
                auth_result_code::BAD_TICKET
            };
        };
        let Some(key) = &self.key else {
            // Ticket presented but no key configured: dev mode accepts, prod mode rejects.
            return if self.allow_unsigned {
                auth_result_code::OK
            } else {
                auth_result_code::BAD_TICKET
            };
        };
        let sig = Signature::from_bytes(&ticket.signature);
        if key.verify_strict(&ticket.payload_bytes(), &sig).is_err() {
            return auth_result_code::BAD_TICKET;
        }
        if now_unix_ms >= ticket.expires_at_ms {
            return auth_result_code::EXPIRED;
        }
        if ticket.region != self.region {
            return auth_result_code::WRONG_REGION;
        }
        auth_result_code::OK
    }
}

fn decode_hex(s: &str) -> Option<Vec<u8>> {
    let s = s.trim();
    if !s.len().is_multiple_of(2) {
        return None;
    }
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).ok())
        .collect()
}

pub fn region_from_string(name: &str) -> u8 {
    use protocol::types::region;
    match name.to_ascii_lowercase().as_str() {
        "europe" => region::EUROPE,
        "us-west" | "us_west" => region::US_WEST,
        "us-east" | "us_east" => region::US_EAST,
        // "local" and anything unknown defaults to ASIA (auth_packet.gd parity).
        _ => region::ASIA,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{Signer, SigningKey};

    fn make_ticket(signing: &SigningKey, expires_at_ms: u64, region: u8) -> Ticket {
        let mut t = Ticket {
            ticket_version: 1,
            character_id: 42,
            region,
            issued_at_ms: 1000,
            expires_at_ms,
            signature: [0; 64],
        };
        t.signature = signing.sign(&t.payload_bytes()).to_bytes();
        t
    }

    fn verifier_for(signing: &SigningKey, allow_unsigned: bool) -> TicketVerifier {
        let hex: String = signing
            .verifying_key()
            .to_bytes()
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect();
        TicketVerifier::new(&hex, allow_unsigned, 0).unwrap()
    }

    #[test]
    fn valid_ticket_accepted() {
        let signing = SigningKey::from_bytes(&[7u8; 32]);
        let v = verifier_for(&signing, false);
        let t = make_ticket(&signing, 60_000, 0);
        assert_eq!(v.verify(Some(&t), 30_000), auth_result_code::OK);
    }

    #[test]
    fn forged_signature_rejected() {
        let signing = SigningKey::from_bytes(&[7u8; 32]);
        let other = SigningKey::from_bytes(&[8u8; 32]);
        let v = verifier_for(&signing, false);
        let t = make_ticket(&other, 60_000, 0);
        assert_eq!(v.verify(Some(&t), 30_000), auth_result_code::BAD_TICKET);
    }

    #[test]
    fn tampered_payload_rejected() {
        let signing = SigningKey::from_bytes(&[7u8; 32]);
        let v = verifier_for(&signing, false);
        let mut t = make_ticket(&signing, 60_000, 0);
        t.character_id = 9999; // tamper after signing
        assert_eq!(v.verify(Some(&t), 30_000), auth_result_code::BAD_TICKET);
    }

    #[test]
    fn expired_and_wrong_region_rejected() {
        let signing = SigningKey::from_bytes(&[7u8; 32]);
        let v = verifier_for(&signing, false);
        let t = make_ticket(&signing, 60_000, 0);
        assert_eq!(v.verify(Some(&t), 60_000), auth_result_code::EXPIRED);
        let t2 = make_ticket(&signing, 60_000, 1);
        assert_eq!(v.verify(Some(&t2), 30_000), auth_result_code::WRONG_REGION);
    }

    #[test]
    fn unsigned_gated_by_dev_mode() {
        let signing = SigningKey::from_bytes(&[7u8; 32]);
        let dev = verifier_for(&signing, true);
        let prod = verifier_for(&signing, false);
        assert_eq!(dev.verify(None, 0), auth_result_code::OK);
        assert_eq!(prod.verify(None, 0), auth_result_code::BAD_TICKET);
    }
}
