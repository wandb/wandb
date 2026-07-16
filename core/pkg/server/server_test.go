package server

import (
	"context"
	"path/filepath"
	"testing"
	"testing/synctest"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/stream"
)

func newDetachedServerForTest(t *testing.T, idleTimeout time.Duration) *Server {
	t.Helper()

	serverLifetimeCtx, stopServer := context.WithCancel(context.Background())
	s := &Server{
		serverLifetimeCtx: serverLifetimeCtx,
		stopServer:        stopServer,
		detached:          true,
		idleTimeout:       idleTimeout,
		streamMux:         stream.NewStreamMux(),
	}

	t.Cleanup(s.stopIdleTimer)
	t.Cleanup(stopServer)

	return s
}

func idleTimerState(s *Server) (hasTimer, shutdownStarted bool) {
	s.idleTimerMu.Lock()
	defer s.idleTimerMu.Unlock()
	return s.idleTimer != nil, s.idleShutdownStarted
}

func TestServer_OnConnectionStartStopsIdleTimer(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		s := newDetachedServerForTest(t, time.Minute)
		s.startIdleTimer()

		if hasTimer, _ := idleTimerState(s); !hasTimer {
			t.Fatal("idle timer was not started")
		}

		s.onConnectionStart()

		if got := s.activeConnections.Load(); got != 1 {
			t.Fatalf("activeConnections = %d, want 1", got)
		}

		if hasTimer, shutdownStarted := idleTimerState(s); hasTimer || shutdownStarted {
			t.Fatalf(
				"idle timer state after connection start = (hasTimer=%t, shutdownStarted=%t), want (false, false)",
				hasTimer,
				shutdownStarted,
			)
		}
	})
}

func TestServer_OnConnectionEndStartsIdleTimer(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		s := newDetachedServerForTest(t, time.Minute)
		s.activeConnections.Store(1)

		s.onConnectionEnd()

		if got := s.activeConnections.Load(); got != 0 {
			t.Fatalf("activeConnections = %d, want 0", got)
		}

		if hasTimer, shutdownStarted := idleTimerState(s); !hasTimer || shutdownStarted {
			t.Fatalf(
				"idle timer state after last connection ended = (hasTimer=%t, shutdownStarted=%t), want (true, false)",
				hasTimer,
				shutdownStarted,
			)
		}
	})
}

func TestServer_IdleTimerStopsServerAfterTimeout(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		s := newDetachedServerForTest(t, time.Second)
		s.startIdleTimer()

		time.Sleep(time.Second)
		synctest.Wait()

		select {
		case <-s.serverLifetimeCtx.Done():
		default:
			t.Fatal("server lifetime context was not canceled")
		}

		if hasTimer, shutdownStarted := idleTimerState(s); hasTimer || !shutdownStarted {
			t.Fatalf(
				"idle timer state after timeout = (hasTimer=%t, shutdownStarted=%t), want (false, true)",
				hasTimer,
				shutdownStarted,
			)
		}
	})
}

func TestServe_ForceStopShutsDownServer(t *testing.T) {
	tempRoot := t.TempDir()
	t.Setenv("TMPDIR", tempRoot)

	portFile := filepath.Join(tempRoot, "port.txt")
	s := NewServer(ServerParams{
		ParentPID: 0,
		Detached:  true,
	})

	srvCh := make(chan error, 1)
	go func() { srvCh <- s.Serve(portFile) }()
	s.ForceStop()

	select {
	case err := <-srvCh:
		require.ErrorIs(t, err, ErrForcedShutdown)
	case <-time.After(5 * time.Second):
		t.Fatal("timed out waiting for Serve() to return")
	}
}
