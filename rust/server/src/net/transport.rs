//! Native ENet UDP socket initialization and non-blocking I/O.
use rusty_enet::{PacketReceived, Socket, SocketOptions, MTU_MAX};
use std::io;
use std::net::{SocketAddr, ToSocketAddrs, UdpSocket};
use std::time::Instant;

#[derive(Debug, Default, serde::Serialize)]
pub struct TransportObservation {
    #[serde(skip)]
    previous_read: Option<Instant>,
    pub read_gaps: crate::measurement::Timing,
    pub receive_calls: u64,
    pub received_datagrams: u64,
    pub receive_errors: u64,
    pub empty_reads: u64,
    pub send_calls: u64,
    pub zero_byte_sends: u64,
    pub send_errors: u64,
}

#[derive(Debug)]
pub struct EnetUdpSocket(UdpSocket, Option<TransportObservation>);

impl EnetUdpSocket {
    pub fn bind(address: impl ToSocketAddrs) -> io::Result<Self> {
        UdpSocket::bind(address).map(|socket| {
            Self(
                socket,
                std::env::var_os("OMEGA_MEASURE_DIR").map(|_| TransportObservation::default()),
            )
        })
    }

    pub fn observation(&self) -> Option<&TransportObservation> {
        self.1.as_ref()
    }
}

impl Socket for EnetUdpSocket {
    type Address = SocketAddr;
    type Error = io::Error;

    fn init(&mut self, options: SocketOptions) -> io::Result<()> {
        <UdpSocket as Socket>::init(&mut self.0, options)?;
        // rusty_enet 0.4's std socket adapter ignores these options. Apply them
        // here so native startup has ENet's intended burst buffering; do not
        // change the transport's non-blocking send/receive behavior.
        let native = socket2::SockRef::from(&self.0);
        native.set_recv_buffer_size(options.receive_buffer)?;
        native.set_send_buffer_size(options.send_buffer)?;
        tracing::info!(
            requested_receive_bytes = options.receive_buffer,
            requested_send_bytes = options.send_buffer,
            effective_receive_bytes = native.recv_buffer_size()?,
            effective_send_bytes = native.send_buffer_size()?,
            "ENet UDP socket buffers initialized"
        );
        Ok(())
    }

    fn send(&mut self, address: SocketAddr, buffer: &[u8]) -> io::Result<usize> {
        let result = <UdpSocket as Socket>::send(&mut self.0, address, buffer);
        if let Some(observation) = &mut self.1 {
            observation.send_calls += 1;
            match &result {
                Ok(0) if !buffer.is_empty() => observation.zero_byte_sends += 1,
                Err(_) => observation.send_errors += 1,
                _ => {}
            }
        }
        result
    }

    fn receive(
        &mut self,
        buffer: &mut [u8; MTU_MAX],
    ) -> io::Result<Option<(SocketAddr, PacketReceived)>> {
        if let Some(observation) = &mut self.1 {
            let now = Instant::now();
            if let Some(previous) = observation.previous_read.replace(now) {
                observation.read_gaps.record(now.duration_since(previous));
            }
            observation.receive_calls += 1;
        }
        let result = <UdpSocket as Socket>::receive(&mut self.0, buffer);
        if let Some(observation) = &mut self.1 {
            match &result {
                Ok(Some(_)) => observation.received_datagrams += 1,
                Ok(None) => observation.empty_reads += 1,
                Err(_) => observation.receive_errors += 1,
            }
        }
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use socket2::SockRef;

    #[test]
    fn init_applies_requested_buffers_and_keeps_nonblocking() {
        let mut socket = EnetUdpSocket::bind(("127.0.0.1", 0)).unwrap();
        socket
            .init(SocketOptions {
                receive_buffer: 16 * 1024,
                send_buffer: 16 * 1024,
            })
            .unwrap();
        let native = SockRef::from(&socket.0);
        // Linux doubles requested sizes for bookkeeping; other platforms may not.
        // A generous bound verifies the request is applied without depending on
        // that accounting convention or accepting an untouched large default.
        assert!((16 * 1024..=64 * 1024).contains(&native.recv_buffer_size().unwrap()));
        assert!((16 * 1024..=64 * 1024).contains(&native.send_buffer_size().unwrap()));
        assert!(socket.receive(&mut [0; MTU_MAX]).unwrap().is_none());
    }

    #[test]
    fn host_startup_uses_enet_buffer_requests() {
        let socket = EnetUdpSocket::bind(("127.0.0.1", 0)).unwrap();
        let host = rusty_enet::Host::new(socket, rusty_enet::HostSettings::default()).unwrap();
        let native = SockRef::from(&host.socket().0);
        assert!(native.recv_buffer_size().unwrap() >= 256 * 1024);
        assert!(native.send_buffer_size().unwrap() >= 256 * 1024);
    }

    #[test]
    fn observed_socket_preserves_datagrams_and_counts_empty_reads() {
        let mut socket = EnetUdpSocket::bind(("127.0.0.1", 0)).unwrap();
        socket.1 = Some(TransportObservation::default());
        socket
            .init(SocketOptions {
                receive_buffer: 16 * 1024,
                send_buffer: 16 * 1024,
            })
            .unwrap();
        let mut buffer = [0; MTU_MAX];
        assert!(socket.receive(&mut buffer).unwrap().is_none());
        let address = socket.0.local_addr().unwrap();
        assert_eq!(socket.send(address, b"diagnostic").unwrap(), 10);
        let deadline = Instant::now() + std::time::Duration::from_secs(1);
        loop {
            if let Some((sender, _)) = socket.receive(&mut buffer).unwrap() {
                assert_eq!(sender, address);
                assert_eq!(&buffer[..10], b"diagnostic");
                break;
            }
            assert!(Instant::now() < deadline, "local datagram not received");
            std::thread::yield_now();
        }
        let observation = socket.observation().unwrap();
        assert_eq!(observation.received_datagrams, 1);
        assert!(observation.empty_reads >= 1);
        assert_eq!(
            observation.receive_calls,
            observation.received_datagrams + observation.empty_reads
        );
        assert_eq!(observation.send_calls, 1);
        assert_eq!(
            observation.send_errors + observation.receive_errors + observation.zero_byte_sends,
            0
        );
    }
}
