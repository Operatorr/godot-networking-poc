use super::{Fault, Replay, Scenario, Wire};
use enet::{EventNoRef, Host, HostSettings, Packet, PacketReceived, PeerID, Socket, MTU_MAX};
use std::{
    cell::{Cell, RefCell},
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
    wire: Vec<Wire>,
    events: Vec<(u64, u8, Vec<u8>)>,
    scenario: Scenario,
    record: bool,
    faults: u32,
}
struct Endpoint {
    address: SocketAddr,
    link: Rc<RefCell<Link>>,
}
impl Socket for Endpoint {
    type Address = SocketAddr;
    type Error = std::io::Error;
    fn send(&mut self, to: SocketAddr, bytes: &[u8]) -> Result<usize, Self::Error> {
        let mut l = self.link.borrow_mut();
        let now = l.clock.get();
        // Fault only a client datagram containing two real 22-byte inputs.
        let input_markers =
            if !matches!(l.scenario.fault, Fault::None) && self.address.port() == 9001 {
                bytes
                    .windows(5)
                    .filter(|b| b[0] == 2 && b[2..5] == [0x7a, 0x51, 0x45])
                    .count()
            } else {
                0
            };
        let inject = self.address.port() == 9001 && input_markers >= 2 && l.faults == 0;
        let result = if inject {
            match l.scenario.fault {
                Fault::Zero => 0,
                Fault::Partial => 1,
                Fault::Error => -1,
                Fault::None => bytes.len() as i32,
            }
        } else {
            bytes.len() as i32
        };
        if inject && !matches!(l.scenario.fault, Fault::None) {
            l.faults += 1;
        }
        if l.record {
            l.wire.push(Wire {
                at: now,
                from: self.address.port(),
                to: to.port(),
                bytes: bytes.to_vec(),
                result,
            });
        }
        if result < 0 {
            return Err(std::io::Error::from(std::io::ErrorKind::Other));
        }
        if result as usize != bytes.len() {
            return Ok(result as usize);
        }
        let delay = if l.scenario.jitter
            && self.address.port() == 9000
            && now >= 70000
            && (now / 500) % 4 == 0
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
        buffer: &mut [u8; MTU_MAX],
    ) -> Result<Option<(SocketAddr, PacketReceived)>, Self::Error> {
        let mut l = self.link.borrow_mut();
        let now = l.clock.get();
        if let Some(i) = l
            .frames
            .iter()
            .position(|f| f.to == self.address && f.due <= now)
        {
            let f = l.frames.remove(i);
            buffer[..f.bytes.len()].copy_from_slice(&f.bytes);
            Ok(Some((f.from, PacketReceived::Complete(f.bytes.len()))))
        } else {
            Ok(None)
        }
    }
}
pub(super) fn run(scenario: Scenario, enabled: bool, record: bool) -> Replay {
    let clock = Rc::new(Cell::new(10000u64));
    let link = Rc::new(RefCell::new(Link {
        clock: clock.clone(),
        frames: vec![],
        wire: vec![],
        events: vec![],
        scenario,
        record,
        faults: 0,
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
    enable(&mut client, enabled);
    client.connect(addr(9000), 3, 0).unwrap();
    let mut next = 100u64;
    let mut offered = 0;
    let mut delivered = 0;
    let mut reset_done = false;
    for now in 10000..371000u64 {
        clock.set(now);
        loop {
            let result = server.service().map(|e| e.map(|e| e.no_ref()));
            match result {
                Ok(Some(EventNoRef::Receive {
                    packet, channel_id, ..
                })) => {
                    if packet.data().len() == 22 && packet.data()[0] == 2 {
                        delivered += 1;
                    }
                    if record {
                        link.borrow_mut()
                            .events
                            .push((now, channel_id, packet.data().to_vec()));
                    }
                }
                Ok(Some(EventNoRef::Connect { .. })) => {
                    if record {
                        link.borrow_mut().events.push((now, 254, vec![]));
                    }
                }
                Ok(Some(EventNoRef::Disconnect { .. })) => {
                    if record {
                        link.borrow_mut().events.push((now, 253, vec![]));
                    }
                }
                Ok(None) => break,
                Err(e) => panic!("unexpected server error: {e}"),
            }
        }
        loop {
            match client.service().map(|e| e.map(|e| e.no_ref())) {
                Ok(Some(EventNoRef::Receive {
                    packet, channel_id, ..
                })) => {
                    if record {
                        link.borrow_mut().events.push((
                            now,
                            channel_id + 128,
                            packet.data().to_vec(),
                        ));
                    }
                }
                Ok(Some(EventNoRef::Connect { .. })) => {
                    if record {
                        link.borrow_mut().events.push((now, 252, vec![]));
                    }
                }
                Ok(Some(EventNoRef::Disconnect { .. })) => {
                    if record {
                        link.borrow_mut().events.push((now, 251, vec![]));
                    }
                }
                Ok(None) => break,
                Err(_) => {
                    assert!(matches!(scenario.fault, Fault::Error));
                    break;
                }
            }
        }
        if now < 370000 && client.peer(PeerID(0)).connected() && now >= 10000 + next * 1000 / 30 {
            for extra in 0..if scenario.batch { 3 } else { 1 } {
                let mut bytes = [0u8; 22];
                bytes[0] = 2;
                bytes[1] = (next + extra) as u8;
                bytes[2..5].copy_from_slice(&[0x7a, 0x51, 0x45]);
                client
                    .peer_mut(PeerID(0))
                    .send(2, &Packet::unreliable(bytes.as_slice()))
                    .unwrap();
                offered += 1;
            }
            next += 1;
            if scenario.reset && !reset_done && now > 100000 {
                client.peer_mut(PeerID(0)).reset();
                reset_done = true;
            }
        }
        if now % 3333 == 0 && client.peer(PeerID(0)).connected() {
            client
                .peer_mut(PeerID(0))
                .send(1, &Packet::reliable(&[3u8, 0, 0, 0, 0][..]))
                .unwrap();
        }
    }
    client.peer_mut(PeerID(0)).reset();
    let counts = counts(&client);
    let mut l = link.borrow_mut();
    Replay {
        wire: std::mem::take(&mut l.wire),
        events: std::mem::take(&mut l.events),
        offered,
        delivered,
        counts,
    }
}
