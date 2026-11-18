package server

import (
	"context"
	"net"
	"sync"
	"testing"
	"testing/synctest"

	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/wrapperspb"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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

func TestConnection_InformInitRejectsDisabledHistoryEncodings(t *testing.T) {
	conn := &Connection{
		connLifetimeCtx: context.Background(),
		outChan:         make(chan *spb.ServerResponse, 1),
	}
	conn.handleInformInit("invalid-settings", &spb.ServerInformInitRequest{
		Settings: &spb.Settings{
			XHistoryValueEncodingJson:  wrapperspb.Bool(false),
			XHistoryValueEncodingTyped: wrapperspb.Bool(false),
		},
	})
	response := <-conn.outChan
	require.Equal(t, "invalid-settings", response.RequestId)
	require.Contains(t, response.GetErrorResponse().GetMessage(), "at least one")
}
