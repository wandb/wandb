package server

import (
	"bytes"
	"context"
	"encoding/binary"
	"fmt"
	"log/slog"
	"net"
	"sync"
	"testing"
	"testing/synctest"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// captureDefaultLogs redirects the default logger to the returned buffer
// for the duration of the test.
func captureDefaultLogs(t *testing.T) *bytes.Buffer {
	t.Helper()

	logs := &bytes.Buffer{}
	previous := slog.Default()
	slog.SetDefault(slog.New(slog.NewTextHandler(
		logs, &slog.HandlerOptions{Level: slog.LevelDebug})))
	t.Cleanup(func() { slog.SetDefault(previous) })

	return logs
}

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

func TestConnection_DoesNotLogUnparseableRequestBytes(t *testing.T) {
	const apiKey = "0123456789abcdef0123456789abcdef01234567"

	logs := captureDefaultLogs(t)
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

	request, err := proto.Marshal(&spb.ServerRequest{
		ServerRequestType: &spb.ServerRequest_InformInit{
			InformInit: &spb.ServerInformInitRequest{
				Settings: &spb.Settings{ApiKey: wrapperspb.String(apiKey)},
			},
		},
	})
	require.NoError(t, err)

	// A leading invalid tag makes the request unparseable while keeping the
	// API key in its bytes.
	payload := append([]byte{0xff}, request...)
	frame := &bytes.Buffer{}
	require.NoError(t, binary.Write(frame, binary.LittleEndian, &Header{
		Magic:      byte('W'),
		DataLength: uint32(len(payload)),
	}))
	_, err = frame.Write(payload)
	require.NoError(t, err)

	written := make(chan struct{})
	go func() {
		defer close(written)
		_, _ = clientConn.Write(frame.Bytes())
	}()

	conn.processIncomingData()
	<-written

	assert.Contains(t, logs.String(), "unmarshalling error")
	assert.Contains(t, logs.String(),
		fmt.Sprintf("token_len=%d", len(payload)))
	assert.NotContains(t, logs.String(), apiKey)
}
