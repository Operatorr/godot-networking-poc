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
    /// Reliable, like `Default`, but re-delivers an event that already happened to a peer that
    /// missed it; telemetry does not count it as a new source event.
    Replay,
}

/// The (channel, reliable) pair a staged packet actually goes out on.
pub fn wire_delivery(target: &Target, packet: &ServerPacket) -> (u8, bool) {
    match target {
        Target::Peers {
            delivery: Delivery::Unreliable,
            ..
        } => (protocol::CH_SNAPSHOT, false),
        _ => (packet.channel(), packet.reliable()),
    }
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

    /// Reliable re-delivery of an earlier event to one peer that missed it.
    pub fn send_replay(&mut self, peer: PeerKey, packet: ServerPacket) {
        self.send_to_with(vec![peer], packet, Delivery::Replay);
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn delivery_decides_the_wire_channel() {
        let event = || {
            ServerPacket::GameEvent(protocol::GameEvent {
                event_type: protocol::types::game_event_type::PROJECTILE_FIRED,
                source_id: 1,
                target_id: 10000,
                data: protocol::GameEventData::ProjectileFired {
                    x: 0.0,
                    y: 0.0,
                    fire_tick: 0,
                },
            })
        };
        let mut outbox = Outbox::new();
        outbox.send_to_unreliable(vec![1], event());
        outbox.send_to(vec![1], event());
        outbox.send_replay(1, event());
        let wire: Vec<_> = outbox
            .drain()
            .iter()
            .map(|(target, packet)| wire_delivery(target, packet))
            .collect();
        assert_eq!(
            wire,
            vec![
                (protocol::CH_SNAPSHOT, false),
                (protocol::CH_RELIABLE, true),
                (protocol::CH_RELIABLE, true),
            ]
        );
    }
}
