package server

import (
	"context"
	"net"
	"testing"
	"time"
)

func TestManageConnectionDataReturnsWhenPeerCloses(t *testing.T) {
	serverConn, clientConn := net.Pipe()
	defer func() { _ = serverConn.Close() }()
	defer func() { _ = clientConn.Close() }()

	conn := NewConnection(
		context.Background(),
		func() {},
		ConnectionParams{
			ID:   "test",
			Conn: serverConn,
		},
	)

	done := make(chan struct{})
	go func() {
		conn.ManageConnectionData()
		close(done)
	}()

	if err := clientConn.Close(); err != nil {
		t.Fatalf("Close() returned error: %v", err)
	}

	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("ManageConnectionData did not return after peer closed the connection")
	}
}
