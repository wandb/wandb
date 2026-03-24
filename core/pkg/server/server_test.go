package server

import (
	"context"
	"testing"
	"testing/synctest"
	"time"

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
