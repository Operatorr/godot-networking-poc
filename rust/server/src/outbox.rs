//! Outbound packet staging. World/tick code pushes packets here; the net layer encodes and
//! sends them on the right ENet channel at the end of message handling / each tick — preserving
//! the "a tick's packets for a peer leave together, in order" semantics that BATCH provided
//! (extraction server-tick H10).

use crate::player::PeerKey;
use protocol::ServerPacket;

#[derive(Default)]
pub struct Outbox {
    pub messages: Vec<(Target, ServerPacket)>,
    /// Peers to gracefully disconnect after queued packets flush, with a
    /// `protocol::types::disconnect_reason` code.
    pub kicks: Vec<(PeerKey, u32)>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Target {
    Peer(PeerKey),
    /// All connected peers (matches NetworkManager.broadcast_to_clients, which did not filter
    /// on authentication).
    Broadcast,
}

impl Outbox {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn send(&mut self, peer: PeerKey, packet: ServerPacket) {
        self.messages.push((Target::Peer(peer), packet));
    }

    pub fn broadcast(&mut self, packet: ServerPacket) {
        self.messages.push((Target::Broadcast, packet));
    }

    pub fn kick(&mut self, peer: PeerKey, reason: u32) {
        self.kicks.push((peer, reason));
    }

    pub fn drain(&mut self) -> Vec<(Target, ServerPacket)> {
        std::mem::take(&mut self.messages)
    }
}
