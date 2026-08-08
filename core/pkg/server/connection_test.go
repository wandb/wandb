package server

import (
	"bytes"
	"context"
	"encoding/binary"
	"fmt"
	"log/slog"
	"net"
	"strings"
	"sync"
	"testing"
	"testing/synctest"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// recordedLogs is a slog handler that keeps log output for inspection.
type recordedLogs struct {
	mu      sync.Mutex
	entries []string
}

// captureDefaultLogs sends everything logged to the default logger to the
// returned recorder for the duration of the test.
func captureDefaultLogs(t *testing.T) *recordedLogs {
	t.Helper()

	logs := &recordedLogs{}
	previous := slog.Default()
	slog.SetDefault(slog.New(logs))
	t.Cleanup(func() { slog.SetDefault(previous) })

	return logs
}

func (l *recordedLogs) Enabled(context.Context, slog.Level) bool { return true }

//nolint:gocritic // the slog.Handler interface fixes this signature.
func (l *recordedLogs) Handle(_ context.Context, record slog.Record) error {
	entry := &strings.Builder{}
	entry.WriteString(record.Message)
	record.Attrs(func(attr slog.Attr) bool {
		fmt.Fprintf(entry, " %s=%s", attr.Key, attrText(attr.Value))
		return true
	})

	l.mu.Lock()
	defer l.mu.Unlock()
	l.entries = append(l.entries, entry.String())

	return nil
}

func (l *recordedLogs) WithAttrs([]slog.Attr) slog.Handler { return l }

func (l *recordedLogs) WithGroup(string) slog.Handler { return l }

// String returns all recorded log output.
func (l *recordedLogs) String() string {
	l.mu.Lock()
	defer l.mu.Unlock()
	return strings.Join(l.entries, "\n")
}

// attrText renders a logged value, expanding byte slices into text so that
// credentials inside raw payloads are visible to assertions.
func attrText(value slog.Value) string {
	if raw, ok := value.Any().([]byte); ok {
		return string(raw)
	}
	return value.String()
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

func TestConnection_DoesNotLogRequestContents(t *testing.T) {
	const apiKey = "0123456789abcdef0123456789abcdef01234567"

	logs := captureDefaultLogs(t)
	backend := viewerBackend(t,
		`{"data": {"viewer": {"id": "id", "entity": "myentity"}}}`)
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

	conn.inChan <- &spb.ServerRequest{
		RequestId: "my-request-id",
		ServerRequestType: &spb.ServerRequest_Authenticate{
			Authenticate: &spb.ServerAuthenticateRequest{
				ApiKey:  apiKey,
				BaseUrl: backend.URL,
			},
		},
	}
	close(conn.inChan)

	conn.handleIncomingRequests()

	assert.NotContains(t, logs.String(), apiKey)
	assert.Contains(t, logs.String(), "ServerRequest_Authenticate")
	assert.Contains(t, logs.String(), "my-request-id")
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
