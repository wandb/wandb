package server

import (
	"context"
	"net"
	"sync"
	"testing"
	"testing/synctest"
)

func TestConnection_ManageConnectionDataReturnsWhenPeerCloses(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		serverConn, clientConn := net.Pipe()
		t.Cleanup(func() { _ = serverConn.Close() })
		t.Cleanup(func() { _ = clientConn.Close() })

		conn := NewConnection(
			context.Background(),
			func() {},
			ConnectionParams{
				ID:   "test",
				Conn: serverConn,
			},
		)

		var wg sync.WaitGroup
		wg.Go(func() {
			conn.ManageConnectionData()
		})

		if err := clientConn.Close(); err != nil {
			t.Fatalf("Close() returned error: %v", err)
		}

		wg.Wait()

		select {
		case <-conn.connLifetimeCtx.Done():
		default:
			t.Fatal("connection lifetime context was not canceled")
		}
	})
}

func TestConnection_ManageConnectionDataReturnsWhenServerStops(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		serverLifetimeCtx, stopServer := context.WithCancel(context.Background())
		serverConn, clientConn := net.Pipe()
		t.Cleanup(func() { _ = serverConn.Close() })
		t.Cleanup(func() { _ = clientConn.Close() })

		conn := NewConnection(
			serverLifetimeCtx,
			stopServer,
			ConnectionParams{
				ID:   "test",
				Conn: serverConn,
			},
		)

		var wg sync.WaitGroup
		wg.Go(func() {
			conn.ManageConnectionData()
		})

		stopServer()
		wg.Wait()

		select {
		case <-conn.connLifetimeCtx.Done():
		default:
			t.Fatal("connection lifetime context was not canceled")
		}

		if _, err := clientConn.Read(make([]byte, 1)); err == nil {
			t.Fatal("client connection remained open after server shutdown")
		}
	})
}
