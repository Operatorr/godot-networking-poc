//! Diagnostic-only observation of Omega's 22-byte channel-2 inputs.
//! All storage belongs to the Host, survives peer reset, and is zero-initializable.
//! No transport decision consumes these counters. This is not a production API.

use crate::{ENetHost, ENetOutgoingCommand, ENetPacket, ENetPeer, Socket};

/// Fixed-size cumulative counters for one single-peer diagnostic host.
#[allow(missing_docs)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct InputCounters {
    pub admitted: u64,
    pub pending: u64,
    pub max_pending: u64,
    pub throttle_retired: u64,
    pub reset_retired: u64,
    pub full_handoffs: u64,
    pub zero_handoffs: u64,
    pub partial_handoffs: u64,
    pub error_handoffs: u64,
    /// Accepted inputs outside this observer's unfragmented-unreliable scope.
    pub unknown_dispositions: u64,
    pub accounting_errors: u64,
    /// Completed hook sections; excludes the last elapsed() bookkeeping itself.
    pub completed_hook_ns: u64,
    pub hook_sections: u64,
}

#[derive(Default)]
pub(crate) struct InputDiagnostic {
    pub(crate) enabled: bool,
    pub(crate) counters: InputCounters,
}

#[derive(Clone, Copy)]
pub(crate) enum Disposition {
    Throttle,
    Reset,
    Full,
    Zero,
    Partial,
    Error,
}

impl InputCounters {
    /// Whether all accepted inputs have one observed disposition or remain pending.
    pub fn balanced(&self) -> bool {
        self.accounting_errors == 0
            && self.admitted
                == self.pending
                    + self.throttle_retired
                    + self.reset_retired
                    + self.full_handoffs
                    + self.zero_handoffs
                    + self.partial_handoffs
                    + self.error_handoffs
                    + self.unknown_dispositions
    }
}

#[inline]
unsafe fn is_input(packet: *mut ENetPacket, channel: u8) -> bool {
    channel == 2
        && !packet.is_null()
        && (*packet).data_length == 22
        && !(*packet).data.is_null()
        && *(*packet).data == 2
}

#[inline]
unsafe fn supported(command: *mut ENetOutgoingCommand) -> bool {
    ((*command).command.header.command & crate::ENET_PROTOCOL_COMMAND_MASK as u8)
        == crate::ENET_PROTOCOL_COMMAND_SEND_UNRELIABLE as u8
        && is_input((*command).packet, (*command).command.header.channel_id)
}

#[inline]
unsafe fn finish<S: Socket>(host: *mut ENetHost<S>, start: std::time::Instant) {
    let counters = &mut (*host).input_diagnostic.counters;
    counters.completed_hook_ns += start.elapsed().as_nanos() as u64;
    counters.hook_sections += 1;
}

#[inline]
pub(crate) unsafe fn admit<S: Socket>(
    peer: *mut ENetPeer<S>,
    channel: u8,
    packet: *mut ENetPacket,
    command: u8,
) {
    let host = (*peer).host;
    if !(*host).input_diagnostic.enabled {
        return;
    }
    let start = std::time::Instant::now();
    if is_input(packet, channel) {
        let counters = &mut (*host).input_diagnostic.counters;
        counters.admitted += 1;
        if command & crate::ENET_PROTOCOL_COMMAND_MASK as u8
            == crate::ENET_PROTOCOL_COMMAND_SEND_UNRELIABLE as u8
        {
            counters.pending += 1;
            counters.max_pending = counters.max_pending.max(counters.pending);
        } else {
            counters.unknown_dispositions += 1;
        }
    }
    finish(host, start);
}

#[inline]
pub(crate) unsafe fn remove<S: Socket>(
    peer: *mut ENetPeer<S>,
    command: *mut ENetOutgoingCommand,
    disposition: Disposition,
) {
    let host = (*peer).host;
    if !(*host).input_diagnostic.enabled {
        return;
    }
    let start = std::time::Instant::now();
    if supported(command) {
        let counters = &mut (*host).input_diagnostic.counters;
        if counters.pending == 0 {
            counters.accounting_errors += 1;
        } else {
            counters.pending -= 1;
        }
        match disposition {
            Disposition::Throttle => counters.throttle_retired += 1,
            Disposition::Reset => counters.reset_retired += 1,
            Disposition::Full => counters.full_handoffs += 1,
            Disposition::Zero => counters.zero_handoffs += 1,
            Disposition::Partial => counters.partial_handoffs += 1,
            Disposition::Error => counters.error_handoffs += 1,
        }
    }
    finish(host, start);
}
