//! Passive v1 native-boundary evidence. No transport configuration changes.
//! Input buffers retain the same bytes/kind/channel; their Drop observes ENet retirement.
//! Binary records are fixed 64 bytes, max 16,384 inputs / peer, max 600 seconds.
//! Fields (LE): admission/retirement/attempt ns, ordinal, UDP fingerprint (5*u64),
//! pre throttle/counter, post throttle/counter (4*u32), disposition u32, wire seq u32.
//! Disposition: 1 full socket handoff, 2 zero, 3 partial, 4 error, 5 no attempt.
//! Records are emitted AFTER service with its pre/post whitelist; outside-service
//! retirement uses u32::MAX fields. Counts cover all inputs even if trace caps fail.
use rusty_enet::{Packet, PacketReceived, Peer, Socket, SocketOptions, MTU_MAX};
use std::{
    collections::BTreeMap,
    fs::File,
    hash::Hasher,
    io::{self, BufWriter, Write},
    net::UdpSocket,
    path::Path,
    sync::{Arc, Mutex},
    time::{Instant, SystemTime, UNIX_EPOCH},
};

const MAX_INPUTS: u64 = 16_384;
const MAX_PENDING: usize = 64;
const UNKNOWN: u32 = u32::MAX;
pub const FIELDS: [&str; 12] = [
    "packetThrottle",
    "packetThrottleCounter",
    "packetThrottleLimit",
    "packetThrottleAcceleration",
    "packetThrottleDeceleration",
    "packetThrottleInterval",
    "lastSendTime",
    "lastReceiveTime",
    "roundTripTime",
    "roundTripTimeVariance",
    "reliableDataInTransit",
    "totalWaitingData",
];

/// Numeric fields only. Reject missing, duplicate, nondecimal or out-of-range values.
/// Pointer-valued queue fields are NOT queue lengths; they are never extracted.
pub fn whitelist(debug: &str) -> Option<[u32; 12]> {
    let mut out = [0; 12];
    for (i, field) in FIELDS.iter().enumerate() {
        let key = format!("{field}: ");
        let mut values = debug.match_indices(&key);
        let (at, _) = values.next()?;
        if values.next().is_some() || (at > 0 && !debug[..at].ends_with([',', ' '])) {
            return None;
        }
        let value = debug[at + key.len()..].split([',', '}']).next()?.trim();
        if value.is_empty() || !value.bytes().all(|b| b.is_ascii_digit()) {
            return None;
        }
        out[i] = value.parse().ok()?;
    }
    if out[0] > 32 || out[1] >= 32 || out[2] > 32 {
        return None;
    }
    Some(out)
}
pub fn peer_state<S: Socket>(peer: &Peer<S>) -> Option<[u32; 12]> {
    whitelist(&format!("{peer:?}"))
}
fn utc() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos() as u64
}

#[derive(Clone)]
pub struct Diagnostic(Arc<Mutex<State>>);
struct Entry {
    admitted: u64,
    ordinal: u64,
    bytes: Vec<u8>,
    attempt: u64,
    fingerprint: u64,
    outcome: u32,
    seq: u32,
}
struct State {
    origin: Instant,
    writer: Option<BufWriter<File>>,
    pending: BTreeMap<u64, Entry>,
    retired: Vec<Entry>,
    counts: BTreeMap<&'static str, u64>,
    last: Option<[u32; 12]>,
    pre: Option<[u32; 12]>,
    in_service: bool,
    last_service: Option<Instant>,
    max_service_gap_ns: u64,
    max_service_ns: u64,
    max_pending_age_ns: u64,
    cost_ns: u64,
    throttle_min: u32,
    trace_records: u64,
}
impl State {
    fn inc(&mut self, key: &'static str, n: u64) {
        *self.counts.entry(key).or_default() += n;
    }
    fn write_entry(&mut self, entry: Entry, post: Option<[u32; 12]>) {
        self.inc("retired", 1);
        self.inc(
            match entry.outcome {
                1 => "retired_handoff",
                2 => "retired_zero",
                3 => "retired_partial",
                4 => "retired_error",
                _ => "retired_no_attempt",
            },
            1,
        );
        let age = utc().saturating_sub(entry.admitted);
        self.max_pending_age_ns = self.max_pending_age_ns.max(age);
        let pre = if self.in_service { self.pre } else { None };
        if entry.outcome == 5 {
            // For this classification require exactly one pending input at service entry,
            // precisely one counter step, unchanged native defaults and the predicted skip.
            let explained = pre.zip(post).is_some_and(|(a, b)| {
                self.counts.get("service_entry_pending") == Some(&1)
                    && (a[1] + 7) % 32 == b[1]
                    && b[1] > a[0]
                    && a[2..6] == [32, 2, 2, 5000]
                    && b[2..6] == [32, 2, 2, 5000]
            });
            self.inc(
                if explained {
                    "no_attempt_single_step_throttle_witness"
                } else {
                    "no_attempt_unclassified"
                },
                1,
            );
        }
        if self.trace_records >= MAX_INPUTS || self.origin.elapsed().as_secs() > 600 {
            self.inc("trace_limit", 1);
            return;
        }
        let mut record = [0u8; 64];
        for (i, n) in [
            entry.admitted,
            utc(),
            entry.attempt,
            entry.ordinal,
            entry.fingerprint,
        ]
        .into_iter()
        .enumerate()
        {
            record[i * 8..i * 8 + 8].copy_from_slice(&n.to_le_bytes());
        }
        let a = pre.unwrap_or([UNKNOWN; 12]);
        let b = post.unwrap_or([UNKNOWN; 12]);
        for (i, n) in [a[0], a[1], b[0], b[1], entry.outcome, entry.seq]
            .into_iter()
            .enumerate()
        {
            record[40 + i * 4..44 + i * 4].copy_from_slice(&n.to_le_bytes());
        }
        if let Some(writer) = self.writer.as_mut() {
            if writer.write_all(&record).is_err() {
                self.inc("write_errors", 1);
            }
        }
        self.trace_records += 1;
    }
}
impl Diagnostic {
    pub fn new(path: Option<&Path>) -> io::Result<Self> {
        let writer = path
            .map(|p| File::create_new(p).map(|f| BufWriter::with_capacity(65536, f)))
            .transpose()?;
        Ok(Self(Arc::new(Mutex::new(State {
            origin: Instant::now(),
            writer,
            pending: BTreeMap::new(),
            retired: vec![],
            counts: BTreeMap::new(),
            last: None,
            pre: None,
            in_service: false,
            last_service: None,
            max_service_gap_ns: 0,
            max_service_ns: 0,
            max_pending_age_ns: 0,
            cost_ns: 0,
            throttle_min: 32,
            trace_records: 0,
        }))))
    }
    pub fn from_env(id: u32) -> io::Result<Option<Self>> {
        match std::env::var("OMEGA_NATIVE_DIAG") {
            Err(std::env::VarError::NotPresent) => Ok(None),
            Ok(v) if v == "v1" => {
                let dir = std::env::var_os("OMEGA_MEASURE_DIR").ok_or_else(|| {
                    io::Error::other("native diagnostic requires measurement directory")
                })?;
                Self::new(Some(&Path::new(&dir).join(format!("native-{id}.bin")))).map(Some)
            }
            _ => Err(io::Error::other("unsupported native diagnostic flag")),
        }
    }
    pub fn observe_peer<S: Socket>(&self, peer: &Peer<S>) -> Option<[u32; 12]> {
        let begin = Instant::now();
        let value = peer_state(peer);
        self.0.lock().unwrap().cost_ns += begin.elapsed().as_nanos() as u64;
        value
    }
    pub fn packet(&self, bytes: &[u8]) -> Packet {
        let begin = Instant::now();
        let mut s = self.0.lock().unwrap();
        let ordinal = s.counts.get("created").copied().unwrap_or(0) + 1;
        s.inc("created", 1);
        if s.pending.len() >= MAX_PENDING {
            s.inc("pending_limit", 1);
        } else {
            s.pending.insert(
                ordinal,
                Entry {
                    admitted: utc(),
                    ordinal,
                    bytes: bytes.to_vec(),
                    attempt: 0,
                    fingerprint: 0,
                    outcome: 5,
                    seq: UNKNOWN,
                },
            );
        }
        s.cost_ns += begin.elapsed().as_nanos() as u64;
        drop(s);
        Packet::unreliable(Box::new(TrackedInput {
            bytes: bytes.to_vec(),
            ordinal,
            diagnostic: self.clone(),
        }))
    }
    pub fn admitted(&self) {
        self.0.lock().unwrap().inc("admitted", 1);
    }
    pub fn begin_service(&self, state: Option<[u32; 12]>) -> Instant {
        let begin = Instant::now();
        let mut s = self.0.lock().unwrap();
        if let Some(last) = s.last_service {
            s.max_service_gap_ns = s
                .max_service_gap_ns
                .max(begin.duration_since(last).as_nanos() as u64);
        }
        s.last_service = Some(begin);
        s.pre = state;
        s.in_service = true;
        let n = s.pending.len() as u64;
        s.counts.insert("service_entry_pending", n);
        s.inc("service_calls", 1);
        if state.is_none() && !s.pending.is_empty() {
            s.inc("whitelist_errors", 1);
        }
        if let Some(a) = state {
            s.throttle_min = s.throttle_min.min(a[0]);
            s.last = Some(a);
        }
        s.cost_ns += begin.elapsed().as_nanos() as u64;
        begin
    }
    pub fn end_service(&self, state: Option<[u32; 12]>, started: Instant, error: bool) {
        let begin = Instant::now();
        let mut s = self.0.lock().unwrap();
        s.max_service_ns = s.max_service_ns.max(started.elapsed().as_nanos() as u64);
        if error {
            s.inc("service_errors", 1);
        }
        if state.is_none() && s.counts.get("service_entry_pending").copied().unwrap_or(0) > 0 {
            s.inc("whitelist_errors", 1);
        }
        if let Some(a) = state {
            s.throttle_min = s.throttle_min.min(a[0]);
            s.last = Some(a);
        }
        let retired = std::mem::take(&mut s.retired);
        for entry in retired {
            s.write_entry(entry, state);
        }
        s.in_service = false;
        s.cost_ns += begin.elapsed().as_nanos() as u64;
    }
    pub fn needs_post(&self) -> bool {
        self.0
            .lock()
            .unwrap()
            .counts
            .get("service_entry_pending")
            .copied()
            .unwrap_or(0)
            > 0
    }
    pub fn has_pending(&self) -> bool {
        !self.0.lock().unwrap().pending.is_empty()
    }
    pub fn snapshot(&self) -> serde_json::Value {
        let begin = Instant::now();
        let mut s = self.0.lock().unwrap();
        if let Some(w) = s.writer.as_mut() {
            if w.flush().is_err() {
                s.inc("write_errors", 1);
            }
        }
        let oldest = s
            .pending
            .values()
            .map(|p| utc().saturating_sub(p.admitted))
            .max();
        let states = s
            .last
            .map(|a| FIELDS.iter().zip(a).collect::<BTreeMap<_, _>>());
        s.cost_ns += begin.elapsed().as_nanos() as u64;
        serde_json::json!({"schema":1,"counts":s.counts,"pending_inputs":s.pending.len(),"oldest_pending_ns":oldest,
            "native_outgoing_queue_length":null,"native_reliable_queue_length":null,
            "native_receive_truncation_detection":"unavailable in unchanged std UdpSocket implementation",
            "last_numeric_peer":states,"throttle_min":s.throttle_min,"max_service_gap_ns":s.max_service_gap_ns,
            "max_service_bracket_ns":s.max_service_ns,"max_input_retirement_age_ns":s.max_pending_age_ns,
            "completed_observer_ns":s.cost_ns,"trace_records":s.trace_records,"trace_bytes":s.trace_records*64,
            "trace_max_bytes":MAX_INPUTS*64,"trace_max_seconds":600})
    }
}
struct TrackedInput {
    bytes: Vec<u8>,
    ordinal: u64,
    diagnostic: Diagnostic,
}
impl AsRef<[u8]> for TrackedInput {
    fn as_ref(&self) -> &[u8] {
        &self.bytes
    }
}
impl Drop for TrackedInput {
    fn drop(&mut self) {
        let begin = Instant::now();
        let mut s = self.diagnostic.0.lock().unwrap();
        if let Some(entry) = s.pending.remove(&self.ordinal) {
            if s.in_service {
                s.retired.push(entry);
            } else {
                s.write_entry(entry, None);
            }
        } else {
            s.inc("untracked_retirement", 1);
        }
        s.cost_ns += begin.elapsed().as_nanos() as u64;
    }
}

/// Independent observer: walk ENet framing and decode input bytes with the REAL
/// application codec. Does not use the collector's command descriptor/parser.
pub fn inputs(bytes: &[u8]) -> Result<Vec<(Vec<u8>, u32)>, &'static str> {
    if bytes.len() < 2 {
        return Err("header");
    }
    let header = u16::from_be_bytes([bytes[0], bytes[1]]);
    if header & 0x4000 != 0 {
        return Err("compression");
    }
    let mut at = if header & 0x8000 != 0 { 4 } else { 2 };
    if at > bytes.len() {
        return Err("sent time");
    }
    let mut result = vec![];
    while at < bytes.len() {
        if bytes.len() - at < 4 {
            return Err("command header");
        }
        let kind = bytes[at] & 15;
        let size = match kind {
            1 => 8,
            2 => 48,
            3 => 44,
            4 => 8,
            5 => 4,
            6 => 6,
            7 => 8,
            8 | 12 => 24,
            9 => 8,
            10 => 12,
            11 => 16,
            _ => return Err("command kind"),
        };
        if bytes.len() - at < size {
            return Err("command size");
        }
        let len = match kind {
            6 => u16::from_be_bytes([bytes[at + 4], bytes[at + 5]]) as usize,
            7..=9 | 12 => u16::from_be_bytes([bytes[at + 6], bytes[at + 7]]) as usize,
            _ => 0,
        };
        if bytes.len() - at - size < len {
            return Err("payload size");
        }
        let payload = &bytes[at + size..at + size + len];
        if payload.first() == Some(&2) && matches!(kind, 6 | 7) {
            if bytes[at + 1] != 2
                || len != 22
                || !matches!(
                    protocol::ClientPacket::decode(payload),
                    Ok(protocol::ClientPacket::PlayerInput(_))
                )
            {
                return Err("input codec/mode");
            }
            let seq = if kind == 7 {
                u16::from_be_bytes([bytes[at + 4], bytes[at + 5]])
            } else {
                u16::from_be_bytes([bytes[at + 2], bytes[at + 3]])
            };
            result.push((payload.to_vec(), u32::from(seq)));
        }
        at += size + len;
    }
    Ok(result)
}

pub struct ObservedSocket<S = UdpSocket> {
    pub inner: S,
    pub diagnostic: Option<Diagnostic>,
}
impl<S: Socket> Socket for ObservedSocket<S> {
    type Address = S::Address;
    type Error = S::Error;
    fn init(&mut self, options: SocketOptions) -> Result<(), S::Error> {
        self.inner.init(options)
    }
    fn send(&mut self, address: S::Address, bytes: &[u8]) -> Result<usize, S::Error> {
        // Native operation first; return exactly the same result. No retries.
        let stamp = self.diagnostic.as_ref().map(|_| utc());
        let result = self.inner.send(address, bytes);
        if let Some(d) = &self.diagnostic {
            let begin = Instant::now();
            let mut s = d.0.lock().unwrap();
            s.inc("socket_attempts", 1);
            let outcome = match &result {
                Ok(n) if *n == bytes.len() => 1,
                Ok(0) => 2,
                Ok(_) => 3,
                Err(_) => 4,
            };
            s.inc(
                match outcome {
                    1 => "socket_handoffs",
                    2 => "socket_zero",
                    3 => "socket_partial",
                    _ => "socket_errors",
                },
                1,
            );
            match inputs(bytes) {
                Ok(rows) => {
                    s.inc("socket_input_attempts", rows.len() as u64);
                    if outcome == 1 {
                        s.inc("socket_input_handoffs", rows.len() as u64);
                    }
                    let mut hash = std::collections::hash_map::DefaultHasher::new();
                    hash.write(bytes);
                    for (payload, seq) in rows {
                        if let Some(entry) = s.pending.values_mut().find(|p| p.bytes == payload) {
                            if entry.attempt != 0 {
                                s.inc("duplicate_input_attempt", 1);
                            } else {
                                entry.attempt = stamp.unwrap();
                                entry.fingerprint = hash.finish();
                                entry.outcome = outcome;
                                entry.seq = seq;
                            }
                        } else {
                            s.inc("unmatched_socket_input", 1);
                        }
                    }
                }
                Err(_) => s.inc("parser_errors", 1),
            }
            s.cost_ns += begin.elapsed().as_nanos() as u64;
        }
        result
    }
    fn receive(
        &mut self,
        buffer: &mut [u8; MTU_MAX],
    ) -> Result<Option<(S::Address, PacketReceived)>, S::Error> {
        let result = self.inner.receive(buffer);
        if let Some(d) = &self.diagnostic {
            let begin = Instant::now();
            let mut s = d.0.lock().unwrap();
            match &result {
                Err(_) => s.inc("receive_errors", 1),
                Ok(Some((_, PacketReceived::Partial))) => s.inc("receive_partial", 1),
                _ => {}
            }
            s.cost_ns += begin.elapsed().as_nanos() as u64;
        }
        result
    }
}
