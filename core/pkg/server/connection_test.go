package server

import (
	"context"
	"net"
	"sync"
	"testing"
	"testing/synctest"
	"time"
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

func TestConnection_WaitForAsyncRequestsReturnsWhenWorkDrainsBeforeTimeout(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		serverLifetimeCtx, stopServer := context.WithCancel(context.Background())
		conn := NewConnection(
			serverLifetimeCtx,
			stopServer,
			ConnectionParams{ID: "test"},
		)

		release := make(chan struct{})
		done := make(chan struct{})
		var wg sync.WaitGroup
		wg.Go(func() {
			<-release
		})

		go func() {
			conn.waitForAsyncRequests(&wg, time.Nanosecond)
			close(done)
		}()

		synctest.Wait()

		select {
		case <-done:
			t.Fatal("wait returned before in-flight work drained")
		default:
		}

		close(release)
		synctest.Wait()

		select {
		case <-done:
		default:
			t.Fatal("wait did not return after in-flight work drained")
		}
	})
}

func TestConnection_WaitForAsyncRequestsStopsWaitingAfterShutdownTimeout(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		serverLifetimeCtx, stopServer := context.WithCancel(context.Background())
		conn := NewConnection(
			serverLifetimeCtx,
			stopServer,
			ConnectionParams{ID: "test"},
		)

		var wg sync.WaitGroup
		wg.Add(1)

		stopServer()
		if conn.connLifetimeCtx.Err() == nil {
			t.Fatal("connection lifetime context was not canceled")
		}

		start := time.Now()
		conn.waitForAsyncRequests(&wg, shutdownAsyncRequestTimeout)
		if elapsed := time.Since(start); elapsed != shutdownAsyncRequestTimeout {
			t.Fatalf("wait returned after %v, want %v", elapsed, shutdownAsyncRequestTimeout)
		}

		wg.Done()
		synctest.Wait()
	})
}
