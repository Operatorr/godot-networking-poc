#[path = "../src/native_diagnostic.rs"]
#[allow(dead_code)]
mod native_diagnostic;
use rusty_enet::{EventNoRef, Host, HostSettings, Packet, PacketReceived, PeerID, Socket, MTU_MAX};
use std::{
    cell::{Cell, RefCell},
    convert::Infallible,
    net::SocketAddr,
    rc::Rc,
    time::Duration,
};
struct Frame {
    due: u64,
    from: SocketAddr,
    to: SocketAddr,
    bytes: Vec<u8>,
}
struct Link {
    clock: Rc<Cell<u64>>,
    frames: Vec<Frame>,
    jitter: bool,
    offered: u64,
    wire: u64,
    delivered: u64,
}
struct Endpoint {
    address: SocketAddr,
    link: Rc<RefCell<Link>>,
}
fn input(n: u64) -> Vec<u8> {
    protocol::ClientPacket::PlayerInput(protocol::PlayerInput {
        sequence: n as u8,
        input_flags: 0,
        aim_angle: 0.0,
        position: (0.0, 0.0),
        velocity: (0.0, 0.0),
        cursor: (0.0, 0.0),
        client_render_tick: n as u16,
        client_rtt_ms: 0,
    })
    .encode()
}
impl Socket for Endpoint {
    type Address = SocketAddr;
    type Error = Infallible;
    fn send(&mut self, to: SocketAddr, bytes: &[u8]) -> Result<usize, Infallible> {
        let mut l = self.link.borrow_mut();
        let now = l.clock.get();
        if self.address.port() == 9001 && !native_diagnostic::inputs(bytes).unwrap().is_empty() {
            l.wire += 1;
        }
        let delay = if l.jitter
            && self.address.port() == 9000
            && now >= 70_000
            && (now / 500).is_multiple_of(4)
        {
            25
        } else {
            2
        };
        l.frames.push(Frame {
            due: now + delay,
            from: self.address,
            to,
            bytes: bytes.to_vec(),
        });
        Ok(bytes.len())
    }
    fn receive(
        &mut self,
        buf: &mut [u8; MTU_MAX],
    ) -> Result<Option<(SocketAddr, PacketReceived)>, Infallible> {
        let mut l = self.link.borrow_mut();
        let now = l.clock.get();
        if let Some(i) = l
            .frames
            .iter()
            .position(|f| f.to == self.address && f.due <= now)
        {
            let f = l.frames.remove(i);
            buf[..f.bytes.len()].copy_from_slice(&f.bytes);
            Ok(Some((f.from, PacketReceived::Complete(f.bytes.len()))))
        } else {
            Ok(None)
        }
    }
}
fn run(jitter: bool) {
    let path =
        std::env::temp_dir().join(format!("omega-native-{}-{jitter}.bin", std::process::id()));
    let diagnostic = native_diagnostic::Diagnostic::new(Some(&path)).unwrap();
    let clock = Rc::new(Cell::new(10_000u64));
    let link = Rc::new(RefCell::new(Link {
        clock: clock.clone(),
        frames: vec![],
        jitter,
        offered: 0,
        wire: 0,
        delivered: 0,
    }));
    let addr = |p| format!("127.0.0.1:{p}").parse::<SocketAddr>().unwrap();
    let settings = || {
        let c = clock.clone();
        HostSettings {
            peer_limit: 1,
            channel_limit: 3,
            seed: Some(1),
            time: Box::new(move || Duration::from_millis(c.get())),
            ..Default::default()
        }
    };
    let mut server = Host::new(
        Endpoint {
            address: addr(9000),
            link: link.clone(),
        },
        settings(),
    )
    .unwrap();
    let mut client = Host::new(
        native_diagnostic::ObservedSocket {
            inner: Endpoint {
                address: addr(9001),
                link: link.clone(),
            },
            diagnostic: Some(diagnostic.clone()),
        },
        settings(),
    )
    .unwrap();
    client.connect(addr(9000), 3, 0).unwrap();
    let mut next = 100u64;
    let mut min_throttle = 32;
    let mut below = 0;
    for now in 10_000..371_000 {
        clock.set(now);
        loop {
            match server.service().unwrap().map(|e| e.no_ref()) {
                Some(EventNoRef::Receive { packet, .. })
                    if matches!(
                        protocol::ClientPacket::decode(packet.data()),
                        Ok(protocol::ClientPacket::PlayerInput(_))
                    ) =>
                {
                    link.borrow_mut().delivered += 1
                }
                Some(_) => {}
                None => break,
            }
        }
        loop {
            let before = diagnostic
                .has_pending()
                .then(|| native_diagnostic::peer_state(client.peer(PeerID(0))))
                .flatten();
            let started = diagnostic.begin_service(before);
            let event = client.service().unwrap().map(|e| e.no_ref());
            diagnostic.end_service(
                diagnostic
                    .needs_post()
                    .then(|| native_diagnostic::peer_state(client.peer(PeerID(0))))
                    .flatten(),
                started,
                false,
            );
            if event.is_none() {
                break;
            }
        }
        if now < 370_000 && client.peer(PeerID(0)).connected() && now >= 10_000 + next * 1000 / 30 {
            let payload = input(next);
            client
                .peer_mut(PeerID(0))
                .send(2, &diagnostic.packet(&payload))
                .unwrap();
            link.borrow_mut().offered += 1;
            diagnostic.admitted();
            assert_eq!(
                diagnostic.snapshot()["pending_inputs"],
                1,
                "admitted work is pending until service"
            );
            next += 1;
        }
        // Reliable client one-shots and Baseline ACKs share channel 1.
        if now.is_multiple_of(3333) && client.peer(PeerID(0)).connected() {
            client
                .peer_mut(PeerID(0))
                .send(1, &Packet::reliable(&[3u8, 0, 0, 0, 0][..]))
                .unwrap();
        }
        // The real bot flushes queued sends on its next service() call too.
        if now.is_multiple_of(33) && client.peer(PeerID(0)).connected() {
            let t = native_diagnostic::peer_state(client.peer(PeerID(0))).unwrap()[0];
            min_throttle = min_throttle.min(t);
            below += u64::from(t < 32);
        }
    }
    let l = link.borrow();
    let snapshot = diagnostic.snapshot();
    println!("diagnostic {snapshot}");
    let raw = std::fs::read(&path).unwrap();
    assert_eq!(raw.len() as u64, snapshot["trace_bytes"].as_u64().unwrap());
    assert_eq!(raw.len() as u64 / 64, l.offered);
    assert_eq!(
        raw.chunks_exact(64)
            .filter(|v| u32::from_le_bytes(v[56..60].try_into().unwrap()) == 1)
            .count() as u64,
        l.wire
    );
    std::fs::remove_file(path).unwrap();
    let c = &snapshot["counts"];
    assert_eq!(c["admitted"], l.offered);
    assert_eq!(c["socket_input_handoffs"], l.wire);
    assert_eq!(c["retired_handoff"], l.delivered);
    assert_eq!(snapshot["pending_inputs"], 0);
    for key in [
        "whitelist_errors",
        "parser_errors",
        "unmatched_socket_input",
        "duplicate_input_attempt",
        "no_attempt_unclassified",
    ] {
        assert_eq!(c[key].as_u64().unwrap_or(0), 0, "{key}");
    }
    if jitter {
        assert_eq!(c["retired_no_attempt"], l.offered - l.wire);
        assert_eq!(
            c["no_attempt_single_step_throttle_witness"],
            l.offered - l.wire
        );
    }
    println!(
        "jitter={jitter} offered={} wire={} delivered={} min_throttle={} sampled_below32={}",
        l.offered, l.wire, l.delivered, min_throttle, below
    );
    assert_eq!(
        l.wire, l.delivered,
        "lossless in-memory link must deliver every wire input"
    );
    if jitter {
        assert!(l.wire < l.offered);
        assert!(min_throttle < 32);
    } else {
        assert_eq!(l.wire, l.offered);
    }
}
#[test]
fn actual_codec_admission_retirement_socket_and_lossless_delivery_reconcile() {
    run(false);
    run(true);
}

#[test]
fn socket_wrapper_preserves_init_send_receive_results_and_counts_failures() {
    use native_diagnostic::{Diagnostic, ObservedSocket};
    struct FaultSocket {
        mode: u8,
        initialized: bool,
    }
    impl Socket for FaultSocket {
        type Address = SocketAddr;
        type Error = std::io::Error;
        fn init(&mut self, options: rusty_enet::SocketOptions) -> Result<(), Self::Error> {
            assert_eq!(options.send_buffer, 123);
            self.initialized = true;
            Ok(())
        }
        fn send(&mut self, _: SocketAddr, b: &[u8]) -> Result<usize, Self::Error> {
            assert!(self.initialized);
            match self.mode {
                0 => Ok(0),
                1 => Ok(1),
                2 => Err(std::io::Error::other("injected")),
                _ => Ok(b.len()),
            }
        }
        fn receive(
            &mut self,
            _: &mut [u8; MTU_MAX],
        ) -> Result<Option<(SocketAddr, PacketReceived)>, Self::Error> {
            if self.mode == 0 {
                Ok(Some((
                    "127.0.0.1:1".parse().unwrap(),
                    PacketReceived::Partial,
                )))
            } else {
                Err(std::io::Error::other("injected"))
            }
        }
    }
    let d = Diagnostic::new(None).unwrap();
    let mut socket = ObservedSocket {
        inner: FaultSocket {
            mode: 0,
            initialized: false,
        },
        diagnostic: Some(d.clone()),
    };
    socket
        .init(rusty_enet::SocketOptions {
            send_buffer: 123,
            receive_buffer: 456,
        })
        .unwrap();
    let to = "127.0.0.1:2".parse().unwrap();
    assert_eq!(socket.send(to, &[0]).unwrap(), 0);
    assert!(matches!(
        socket.receive(&mut [0; MTU_MAX]).unwrap(),
        Some((_, PacketReceived::Partial))
    ));
    socket.inner.mode = 1;
    assert_eq!(socket.send(to, &[0, 1]).unwrap(), 1);
    assert!(socket.receive(&mut [0; MTU_MAX]).is_err());
    socket.inner.mode = 2;
    assert!(socket.send(to, &[0, 1]).is_err());
    socket.inner.mode = 3;
    assert_eq!(socket.send(to, &[0, 1]).unwrap(), 2);
    let s = d.snapshot();
    let c = &s["counts"];
    for key in [
        "socket_zero",
        "socket_partial",
        "socket_errors",
        "socket_handoffs",
        "receive_partial",
        "receive_errors",
    ] {
        assert_eq!(c[key], 1, "{key}");
    }
    assert_eq!(c["parser_errors"], 1); // [0] is malformed, the 2-byte empty header is valid.
}

#[test]
fn actual_peer_whitelist_is_numeric_and_fails_closed_on_format_changes() {
    use native_diagnostic::{peer_state, whitelist};
    let host = Host::new(
        std::net::UdpSocket::bind("127.0.0.1:0").unwrap(),
        HostSettings {
            peer_limit: 1,
            ..Default::default()
        },
    )
    .unwrap();
    let peer = host.peer(PeerID(0));
    let text = format!("{peer:?}");
    let fields = peer_state(peer).unwrap();
    assert_eq!(&fields[..6], &[32, 0, 32, 2, 2, 5000]);
    for changed in [
        text.replace("packetThrottle: ", "changed: "),
        text.replace("packetThrottle: 32", "packetThrottle: x"),
        text.replace("packetThrottle: 32", "packetThrottle: 33"),
        text.replace(
            "packetThrottle: 32",
            "packetThrottle: 32, packetThrottle: 32",
        ),
    ] {
        assert!(whitelist(&changed).is_none());
    }
}

#[test]
#[ignore = "manual timing probe; no timing threshold in correctness checks"]
fn profile_actual_peer_numeric_observer() {
    let host = Host::new(
        std::net::UdpSocket::bind("127.0.0.1:0").unwrap(),
        HostSettings {
            peer_limit: 1,
            ..Default::default()
        },
    )
    .unwrap();
    let peer = host.peer(PeerID(0));
    let count = 100_000;
    let started = std::time::Instant::now();
    for _ in 0..count {
        std::hint::black_box(native_diagnostic::peer_state(std::hint::black_box(peer)).unwrap());
    }
    println!(
        "numeric_peer_observer calls={count} ns_per_call={}",
        started.elapsed().as_nanos() / count
    );
}
