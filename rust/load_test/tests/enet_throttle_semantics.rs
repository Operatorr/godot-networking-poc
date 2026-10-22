//! Transport-semantic witness using the pinned ENet engine, virtual time and a lossless link.
//! A queued unreliable input can be discarded by ENet's adaptive throttle before Socket::send.
//! This is not attribution of a historical host run or a change to throttle settings.
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
const MAGIC: &[u8] = b"OMEGA_INPUT_PROBE";
impl Socket for Endpoint {
    type Address = SocketAddr;
    type Error = Infallible;
    fn send(&mut self, to: SocketAddr, bytes: &[u8]) -> Result<usize, Infallible> {
        let mut l = self.link.borrow_mut();
        let now = l.clock.get();
        if self.address.port() == 9001 && bytes.windows(MAGIC.len()).any(|v| v == MAGIC) {
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
fn throttle(host: &Host<Endpoint>) -> u32 {
    let s = format!("{:?}", host.peer(PeerID(0)));
    s.split("packetThrottle: ")
        .nth(1)
        .unwrap()
        .split(',')
        .next()
        .unwrap()
        .parse()
        .unwrap()
}
fn run(jitter: bool) {
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
        Endpoint {
            address: addr(9001),
            link: link.clone(),
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
                Some(EventNoRef::Receive { packet, .. }) if packet.data().starts_with(MAGIC) => {
                    link.borrow_mut().delivered += 1
                }
                Some(_) => {}
                None => break,
            }
        }
        while client.service().unwrap().is_some() {}
        if now < 370_000 && client.peer(PeerID(0)).connected() && now >= 10_000 + next * 1000 / 30 {
            let mut payload = MAGIC.to_vec();
            payload.extend_from_slice(&(next as u32).to_be_bytes());
            client
                .peer_mut(PeerID(0))
                .send(2, &Packet::unreliable(payload.as_slice()))
                .unwrap();
            link.borrow_mut().offered += 1;
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
            let t = throttle(&client);
            min_throttle = min_throttle.min(t);
            below += u64::from(t < 32);
        }
    }
    let l = link.borrow();
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
fn unreliable_queue_admission_is_not_a_wire_send_guarantee() {
    run(false);
    run(true);
}
