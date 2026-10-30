//! Outbound packet staging. World/tick code pushes packets here; the net layer encodes and
//! sends them on the right ENet channel at the end of message handling / each tick — preserving
//! the "a tick's packets for a peer leave together, in order" semantics that BATCH provided
//! (extraction server-tick H10).

use crate::player::PeerKey;
use protocol::ServerPacket;
use tracing::warn;

/// Soft cap on staged messages before a flush. At 30 Hz over up to ~1000 peers a normal tick
/// stages low tens of thousands of packets; this only trips if the send loop stalls and the
/// outbox grows unbounded. We log once per crossing and keep going (dropping would corrupt the
/// delta stream) — the warn is the alarm that the net layer isn't draining.
const MESSAGE_SOFT_CAP: usize = 200_000;
/// Kicks are rare (one per disconnecting peer); a backlog past this is pathological.
const KICK_SOFT_CAP: usize = 10_000;

#[derive(Default)]
pub struct Outbox {
    pub messages: Vec<(Target, ServerPacket)>,
    /// Peers to gracefully disconnect after queued packets flush, with a
    /// `protocol::types::disconnect_reason` code.
    pub kicks: Vec<(PeerKey, u32)>,
    /// Latched so the soft-cap warn fires once per crossing, not every push.
    over_message_cap: bool,
    over_kick_cap: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Delivery {
    /// Whatever `ServerPacket::reliable()` / `channel()` say for the packet type.
    Default,
    /// Force unreliable-sequenced on the Snapshot channel. Only for events whose effect the
    /// next Snapshot reproduces (an authoritative-recovery guarantee the caller has validated).
    Unreliable,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Target {
    Peer(PeerKey),
    /// All connected peers (matches NetworkManager.broadcast_to_clients, which did not filter
    /// on authentication).
    Broadcast,
    /// An explicit recipient set — the AoI-scoped alternative to `Broadcast` for events that
    /// only matter to peers who can see where they happened (see `PlayerManager::aoi_recipients`).
    Peers {
        peers: Vec<PeerKey>,
        delivery: Delivery,
    },
}

impl Outbox {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn send(&mut self, peer: PeerKey, packet: ServerPacket) {
        self.messages.push((Target::Peer(peer), packet));
        self.check_message_cap();
    }

    pub fn broadcast(&mut self, packet: ServerPacket) {
        self.messages.push((Target::Broadcast, packet));
        self.check_message_cap();
    }

    /// Reliable delivery to an explicit recipient set (AoI-scoped event). An empty set stages
    /// nothing.
    pub fn send_to(&mut self, peers: Vec<PeerKey>, packet: ServerPacket) {
        self.send_to_with(peers, packet, Delivery::Default);
    }

    /// Unreliable-sequenced delivery (Snapshot channel) to an explicit recipient set. The next
    /// Snapshot must carry everything a receiver needs if this packet is lost.
    pub fn send_to_unreliable(&mut self, peers: Vec<PeerKey>, packet: ServerPacket) {
        self.send_to_with(peers, packet, Delivery::Unreliable);
    }

    fn send_to_with(&mut self, peers: Vec<PeerKey>, packet: ServerPacket, delivery: Delivery) {
        if peers.is_empty() {
            return;
        }
        self.messages
            .push((Target::Peers { peers, delivery }, packet));
        self.check_message_cap();
    }

    pub fn kick(&mut self, peer: PeerKey, reason: u32) {
        self.kicks.push((peer, reason));
        if self.kicks.len() > KICK_SOFT_CAP {
            if !self.over_kick_cap {
                warn!(
                    "outbox kick queue exceeded soft cap ({}); send loop may be stalled",
                    KICK_SOFT_CAP
                );
                self.over_kick_cap = true;
            }
        } else {
            self.over_kick_cap = false;
        }
    }

    fn check_message_cap(&mut self) {
        if self.messages.len() > MESSAGE_SOFT_CAP {
            if !self.over_message_cap {
                warn!(
                    "outbox message queue exceeded soft cap ({}); send loop may be stalled",
                    MESSAGE_SOFT_CAP
                );
                self.over_message_cap = true;
            }
        } else {
            self.over_message_cap = false;
        }
    }

    pub fn drain(&mut self) -> Vec<(Target, ServerPacket)> {
        self.over_message_cap = false;
        std::mem::take(&mut self.messages)
    }
}
