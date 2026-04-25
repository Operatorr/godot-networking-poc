package handlers

import (
	"errors"
	"net"
	"testing"
	"time"
)

func TestIsWebSocketServerOnline(t *testing.T) {
	previousDialTCP := dialTCP
	defer func() {
		dialTCP = previousDialTCP
	}()

	dialTCP = func(network string, address string, timeout time.Duration) (net.Conn, error) {
		if network != "tcp" {
			t.Fatalf("expected tcp network, got %q", network)
		}
		if address != "127.0.0.1:9001" {
			t.Fatalf("expected websocket address, got %q", address)
		}
		if timeout != time.Second {
			t.Fatalf("expected timeout to be passed through, got %v", timeout)
		}
		return noopConn{}, nil
	}

	if !isWebSocketServerOnline("ws://127.0.0.1:9001", time.Second) {
		t.Fatal("expected listening websocket endpoint to be online")
	}
}

func TestIsWebSocketServerOnlineRejectsInvalidURL(t *testing.T) {
	previousDialTCP := dialTCP
	defer func() {
		dialTCP = previousDialTCP
	}()

	dialTCP = func(_ string, _ string, _ time.Duration) (net.Conn, error) {
		t.Fatal("invalid URLs should not dial")
		return nil, errors.New("unexpected dial")
	}

	if isWebSocketServerOnline("http://127.0.0.1:1", 10*time.Millisecond) {
		t.Fatal("expected non-websocket URL to be offline")
	}
	if isWebSocketServerOnline("ws://", 10*time.Millisecond) {
		t.Fatal("expected websocket URL without host to be offline")
	}
}

func TestIsWebSocketServerOnlineReturnsOfflineWhenDialFails(t *testing.T) {
	previousDialTCP := dialTCP
	defer func() {
		dialTCP = previousDialTCP
	}()

	dialTCP = func(_ string, _ string, _ time.Duration) (net.Conn, error) {
		return nil, errors.New("connection refused")
	}

	if isWebSocketServerOnline("ws://127.0.0.1:9001", time.Second) {
		t.Fatal("expected failed dial to be offline")
	}
}

type noopConn struct{}

func (noopConn) Read(_ []byte) (int, error) {
	return 0, errors.New("not implemented")
}

func (noopConn) Write(_ []byte) (int, error) {
	return 0, errors.New("not implemented")
}

func (noopConn) Close() error {
	return nil
}

func (noopConn) LocalAddr() net.Addr {
	return &net.TCPAddr{}
}

func (noopConn) RemoteAddr() net.Addr {
	return &net.TCPAddr{}
}

func (noopConn) SetDeadline(_ time.Time) error {
	return nil
}

func (noopConn) SetReadDeadline(_ time.Time) error {
	return nil
}

func (noopConn) SetWriteDeadline(_ time.Time) error {
	return nil
}
