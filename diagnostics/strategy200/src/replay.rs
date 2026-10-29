//! Actual pinned Bot + ENet, virtual clock and in-memory sockets. No network I/O.
#![allow(dead_code)]
#[path = "../assertions.rs"] mod assertions;
#[path = "../behavior.rs"] mod behavior;
#[path = "../bot.rs"] mod bot;
#[path = "../measurement.rs"] mod measurement;
#[path = "../metrics.rs"] mod metrics;
#[path = "../native_diagnostic.rs"] mod native_diagnostic;
#[path = "../bot_reference.rs"] mod reference;
#[path = "../rng.rs"] mod rng;
#[path = "../sweep.rs"] mod sweep;

use rusty_enet::{EventNoRef, Host, HostSettings, Packet, PacketReceived, PeerID, Socket, MTU_MAX};
use protocol::{AuthOk, AuthResult, ClientPacket, EntityRecord, GameEvent, GameEventData, ServerPacket, Snapshot};
use serde_json::{json, Value};
use std::{cell::{Cell, RefCell}, collections::{BTreeMap, VecDeque}, io::Write, net::SocketAddr, rc::Rc, time::{Duration, Instant}};

type Trace = Vec<(u64, u8, Vec<u8>)>;
#[derive(Debug, PartialEq)]
struct Wire { at: u64, from: u16, to: u16, bytes: Vec<u8> }
struct Frame { from: SocketAddr, due: u64, bytes: Vec<u8> }
struct Link {
    clock: Rc<Cell<u64>>,
    queues: BTreeMap<u16, VecDeque<Frame>>,
    wire: Vec<Wire>,
    record: bool,
    fail_port: Option<u16>,
}
struct Endpoint { address: SocketAddr, link: Rc<RefCell<Link>> }
impl Socket for Endpoint {
    type Address = SocketAddr;
    type Error = std::io::Error;
    fn send(&mut self, to: SocketAddr, bytes: &[u8]) -> Result<usize, Self::Error> {
        let mut l = self.link.borrow_mut();
        let now = l.clock.get();
        if l.record { l.wire.push(Wire { at: now, from: self.address.port(), to: to.port(), bytes: bytes.to_vec() }); }
        l.queues.entry(to.port()).or_default().push_back(Frame { from: self.address, due: now + 1, bytes: bytes.to_vec() });
        Ok(bytes.len())
    }
    fn receive(&mut self, buffer: &mut [u8; MTU_MAX]) -> Result<Option<(SocketAddr, PacketReceived)>, Self::Error> {
        let mut l = self.link.borrow_mut();
        if l.fail_port == Some(self.address.port()) {
            l.fail_port = None;
            return Err(std::io::Error::other("synthetic receive failure"));
        }
        let now = l.clock.get();
        let q = l.queues.entry(self.address.port()).or_default();
        if q.front().is_some_and(|f| f.due <= now) {
            let f = q.pop_front().unwrap();
            buffer[..f.bytes.len()].copy_from_slice(&f.bytes);
            Ok(Some((f.from, PacketReceived::Complete(f.bytes.len()))))
        } else { Ok(None) }
    }
}
trait Driver: Sized {
    fn create(host: Host<native_diagnostic::ObservedSocket<Endpoint>>, id: u32, budget: usize, record: bool) -> Self;
    fn poll(&mut self, now: f64);
    fn begin_disconnect(&mut self, now: f64);
    fn force_close(&mut self);
    fn trace(&self) -> Trace;
    fn metrics(&self) -> &metrics::BotMetrics;
    fn terminal(&self) -> bool;
}
macro_rules! driver {
    ($m:ident, $set:expr) => {
        impl Driver for $m::Bot<Endpoint> {
            fn create(host: Host<native_diagnostic::ObservedSocket<Endpoint>>, id: u32, budget: usize, record: bool) -> Self {
                let mut b = Self::from_host(host, id, addr(9000), behavior::BehaviorKind::Strategy, 1.0, 30.0, 120000, Some(30), None, 0.0).unwrap();
                ($set)(&mut b, budget);
                b.replay_trace = record.then(Vec::new);
                b
            }
            fn poll(&mut self, now: f64) { self.poll(now) }
            fn begin_disconnect(&mut self, now: f64) { self.begin_disconnect(now) }
            fn force_close(&mut self) { self.force_close() }
            fn trace(&self) -> Trace { self.replay_trace.clone().unwrap_or_default() }
            fn metrics(&self) -> &metrics::BotMetrics { &self.metrics }
            fn terminal(&self) -> bool { self.is_terminal() }
        }
    }
}
driver!(reference, |_: &mut reference::Bot<Endpoint>, _: usize| {});
driver!(bot, |b: &mut bot::Bot<Endpoint>, budget| b.event_budget = budget);

#[derive(Clone, Copy, Debug)]
enum Scenario { Stable, Burst, Sustained, LateBurst, ReceiveError, Timeout, Malformed, Teardown }
#[derive(Debug, PartialEq)]
struct Outcome { wire: Vec<Wire>, traces: Vec<Trace>, states: Vec<Value>, max_receive_batch: u64, offered: u64, generated: u64 }
fn addr(port: u16) -> SocketAddr { ([127,0,0,1], port).into() }
fn settings(clock: Rc<Cell<u64>>, peers: usize, seed: u32) -> HostSettings {
    HostSettings { peer_limit: peers, channel_limit: 3, seed: Some(seed), time: Box::new(move || Duration::from_millis(clock.get())), ..Default::default() }
}
fn send(server: &mut Host<Endpoint>, peer: PeerID, packet: &ServerPacket, reliable: bool) {
    let bytes = packet.encode();
    let p = if reliable { Packet::reliable(bytes) } else { Packet::unreliable(bytes) };
    server.peer_mut(peer).send(if reliable { 1 } else { 0 }, &p).unwrap();
}

fn run<B: Driver>(scenario: Scenario, budget: usize, record: bool, observed: bool, count: usize, mut recorder: Option<&mut measurement::Recorder>) -> Outcome {
    assert!(recorder.is_none(), "generic reference path does not export ordinary rows");
    recorder.take();
    run_core::<B>(scenario, budget, record, observed, count, None)
}

// Recorder callback permits actual ordinary BotObservation serialization in the
// timing arm without altering the reference Bot or its application behavior.
type Export<B> = Box<dyn FnMut(&[B], f64, &str)>;
fn run_core<B: Driver>(scenario: Scenario, budget: usize, record: bool, observed: bool, count: usize, mut export: Option<Export<B>>) -> Outcome {
    sweep::configure_replay(observed);
    let clock = Rc::new(Cell::new(10000));
    let link = Rc::new(RefCell::new(Link { clock: clock.clone(), queues: BTreeMap::new(), wire: vec![], record, fail_port: None }));
    let mut server = Host::new(Endpoint { address: addr(9000), link: link.clone() }, settings(clock.clone(), count, 77)).unwrap();
    let mut bots: Vec<B> = (1..=count).map(|id| {
        let host = Host::new(native_diagnostic::ObservedSocket { inner: Endpoint { address: addr(10000 + id as u16), link: link.clone() }, diagnostic: None }, settings(clock.clone(),1,id as u32)).unwrap();
        B::create(host, id as u32, budget, record)
    }).collect();
    let duration = if matches!(scenario, Scenario::Timeout) { 16000 } else { 11000 };
    let mut offered = 0;
    let mut generated = 0;
    let mut max_receive_batch = 0;
    let mut closing = false;
    for elapsed in 0..duration + 2000 {
        let ms = 10000 + elapsed;
        clock.set(ms);
        if elapsed == 700 && matches!(scenario, Scenario::ReceiveError) { link.borrow_mut().fail_port = Some(10001); }
        while let Some(event) = server.service().unwrap().map(|e| e.no_ref()) {
            if let EventNoRef::Receive { peer, packet, .. } = event {
                match ClientPacket::decode(packet.data()) {
                    Ok(ClientPacket::ConnectAuth(_)) if !matches!(scenario, Scenario::Timeout) => send(&mut server, peer, &ServerPacket::AuthResult(AuthResult { result: 0, ok: Some(AuthOk { entity_id: peer.0 as u16 + 1, server_tick: 0, tick_rate: 30 }) }), true),
                    Ok(ClientPacket::PlayerInput(_)) => offered += 1,
                    _ => {}
                }
            }
        }
        if elapsed < duration {
            if elapsed % 34 == 0 && !matches!(scenario, Scenario::Timeout) {
                for i in 0..count {
                    if server.peer(PeerID(i)).connected() {
                        send(&mut server, PeerID(i), &ServerPacket::Snapshot(Snapshot { server_tick: elapsed as u32 / 34, server_ms: elapsed as u32, is_baseline: true, baseline_tick: None,
                            entities: vec![EntityRecord::full(i as u16 + 1, (0.0,0.0),0,0), EntityRecord::full(30001, (200.0,0.0),0,0)] }), true);
                    }
                }
            }
            let amount = match scenario {
                Scenario::Burst if elapsed == 500 => 512,
                Scenario::Sustained if (500..550).contains(&elapsed) => 64,
                Scenario::LateBurst if elapsed == duration - 2 => 512,
                _ => 0
            };
            for _ in 0..amount {
                generated += 1;
                send(&mut server, PeerID(0), &ServerPacket::GameEvent(GameEvent { event_type: protocol::game_event_type::CHAT_MESSAGE, source_id: 999, target_id: generated as u16, data: GameEventData::None }), true);
            }
            if elapsed == 600 && matches!(scenario, Scenario::Malformed) {
                server.peer_mut(PeerID(0)).send(1, &Packet::reliable(vec![255])).unwrap();
            }
            if elapsed == 600 && matches!(scenario, Scenario::Teardown) {
                server.peer_mut(PeerID(0)).disconnect(protocol::disconnect_reason::SERVER_SHUTDOWN);
            }
        } else if !closing {
            if let Some(export) = &mut export { export(&bots, elapsed as f64 / 1000.0, "end"); }
            for b in &mut bots { b.begin_disconnect(elapsed as f64 / 1000.0); }
            closing = true;
        }
        let started = sweep::global_start();
        for b in &mut bots {
            let before = b.metrics().packets_received;
            b.poll(elapsed as f64 / 1000.0);
            let n = b.metrics().packets_received - before;
            max_receive_batch = max_receive_batch.max(n);
            if budget != 0 { assert!(n <= budget as u64, "event budget exceeded"); }
        }
        sweep::global_finish(started, count);
        if elapsed < duration && elapsed % 1000 == 0 {
            if let Some(export) = &mut export { export(&bots, elapsed as f64 / 1000.0, if elapsed == 0 { "start" } else { "" }); }
        }
        server.flush();
    }
    for b in &mut bots { b.force_close(); }
    if let Some(export) = &mut export { export(&bots, (duration + 2000) as f64 / 1000.0, "drained"); }
    let result = Outcome {
        wire: std::mem::take(&mut link.borrow_mut().wire),
        traces: bots.iter().map(Driver::trace).collect(),
        states: bots.iter().map(|b| json!({"terminal":b.terminal(), "metrics":b.metrics().summary()})).collect(),
        max_receive_batch, offered, generated
    };
    std::hint::black_box(&result);
    result
}

fn parity() {
    std::env::remove_var("OMEGA_MEASURE_DIR");
    std::env::remove_var("OMEGA_NATIVE_DIAG");
    for scenario in [Scenario::Stable, Scenario::Burst, Scenario::Sustained, Scenario::LateBurst, Scenario::ReceiveError, Scenario::Timeout, Scenario::Malformed, Scenario::Teardown] {
        let reference = run::<reference::Bot<Endpoint>>(scenario,0,true,false,3,None);
        let off = run::<bot::Bot<Endpoint>>(scenario,0,true,false,3,None);
        assert_eq!(reference, off, "disabled parity failed: {scenario:?}");
        let on = run::<bot::Bot<Endpoint>>(scenario,32,true,false,3,None);
        let observed = run::<bot::Bot<Endpoint>>(scenario,32,true,true,3,None);
        if matches!(scenario, Scenario::LateBurst) {
            println!("{}", json!({"scenario":"LateBurst-boundary-witness", "off_max_batch":off.max_receive_batch,"on_max_batch":on.max_receive_batch,"generated_events":on.generated,"off_game_events":off.states[0]["metrics"]["game_events_received"],"on_game_events":on.states[0]["metrics"]["game_events_received"],"off_first_peer_trace":off.traces[0],"on_first_peer_trace":on.traces[0]}));
        }
        assert_eq!(on, observed, "observer changed virtual replay: {scenario:?}");
        if matches!(scenario, Scenario::Stable | Scenario::ReceiveError | Scenario::Timeout | Scenario::Malformed | Scenario::Teardown) {
            assert_eq!(off, on, "unbacklogged behavior differs: {scenario:?}");
        } else {
            for (a,b) in off.traces.iter().zip(&on.traces) {
                let received = |trace: &Trace| trace.iter().filter(|(_,k,_)| *k < 250).map(|(_,k,b)| (*k,b.clone())).collect::<Vec<_>>();
                assert_eq!(received(a), received(b), "received event order/loss: {scenario:?}");
            }
            assert!(off.max_receive_batch > 32);
            assert_eq!(on.max_receive_batch,32);
            assert_eq!(on.states[0]["metrics"]["game_events_received"], on.generated);
        }
        if matches!(scenario, Scenario::Stable) {
            assert!(on.offered > 3 * 256, "input sequence wrap not exercised");
        }
        println!("{}", json!({"scenario":format!("{scenario:?}"), "disabled_parity":true, "observer_parity":true, "events_ordered":true, "off_max_batch":off.max_receive_batch, "on_max_batch":on.max_receive_batch, "offered_inputs":on.offered, "generated_burst_events":on.generated}));
    }
}

fn timing(out: &std::path::Path) {
    std::fs::create_dir(out).expect("fresh timing directory required");
    std::env::remove_var("OMEGA_NATIVE_DIAG");
    let mut values = vec![];
    // Fixed five pairs; no warmup results, discarded pair or retry.
    for pair in 0..5 {
        for observed in if pair % 2 == 0 { [false,true] } else { [true,false] } {
            let directory = out.join(format!("pair{pair}-{}",if observed { "enabled" } else { "disabled" }));
            std::env::set_var("OMEGA_MEASURE_DIR", &directory);
            let start = Instant::now();
            let mut recorder = measurement::Recorder::from_env().unwrap();
            let export: Export<bot::Bot<Endpoint>> = Box::new(move |bots, seconds, boundary| recorder.sample(bots, seconds, boundary));
            let outcome = run_core::<bot::Bot<Endpoint>>(Scenario::Stable,32,false,observed,200,Some(export));
            let ns = start.elapsed().as_nanos();
            let row = json!({"pair":pair,"enabled":observed,"elapsed_ns":ns,"offered_inputs":outcome.offered,"observer":sweep::global_snapshot()});
            println!("{row}"); std::io::stdout().flush().unwrap();
            values.push(row);
        }
    }
    let total = |enabled| values.iter().filter(|r|r["enabled"]==enabled).map(|r|r["elapsed_ns"].as_u64().unwrap() as u128).sum::<u128>();
    let off = total(false); let on = total(true);
    let passed = on * 100 <= off * 102;
    let result = json!({"pairs":values,"disabled_total_ns":off,"enabled_total_ns":on,"overhead_percent":100.0*(on as f64/off as f64-1.0),"limit_percent":2,"passed":passed,"network_sockets_opened":0,"remote_commands":0,"remote_attempt_slots_consumed":0});
    std::fs::write(out.join("assessment.json"),serde_json::to_vec_pretty(&result).unwrap()).unwrap();
    println!("{result}");
    if !passed { std::process::exit(1); }
}
fn main() {
    match std::env::args().nth(1).as_deref() {
        Some("parity") => parity(),
        Some("timing") => timing(&std::path::PathBuf::from(std::env::args().nth(2).expect("output directory"))),
        _ => panic!("usage: poll-replay parity | timing FRESH_DIRECTORY"),
    }
}
