//! Native ENet UDP socket initialization and non-blocking I/O.
use rusty_enet::{PacketReceived, Socket, SocketOptions, MTU_MAX};
use std::io;
use std::net::{SocketAddr, ToSocketAddrs, UdpSocket};

#[derive(Debug)]
pub struct EnetUdpSocket(UdpSocket);

impl EnetUdpSocket {
    pub fn bind(address: impl ToSocketAddrs) -> io::Result<Self> {
        UdpSocket::bind(address).map(Self)
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
        <UdpSocket as Socket>::send(&mut self.0, address, buffer)
    }

    fn receive(
        &mut self,
        buffer: &mut [u8; MTU_MAX],
    ) -> io::Result<Option<(SocketAddr, PacketReceived)>> {
        <UdpSocket as Socket>::receive(&mut self.0, buffer)
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
}
