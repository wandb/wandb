package leet_test

import (
	"sync/atomic"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestHeartbeatManager_StartsAndSendsMessages(t *testing.T) {
	logger := observability.NewNoOpLogger()
	wcChan := make(chan tea.Msg, 10)

	hm := leet.NewHeartbeatManager(100*time.Millisecond, wcChan, logger)

	isRunning := func() bool { return true }
	hm.Start(isRunning)

	// Wait for heartbeat
	select {
	case msg := <-wcChan:
		_, ok := msg.(leet.HeartbeatMsg)
		require.True(t, ok, "expected HeartbeatMsg")
	case <-time.After(200 * time.Millisecond):
		t.Fatal("heartbeat not received within timeout")
	}

	hm.Stop()
}

func TestHeartbeatManager_DoesNotStartWhenNotRunning(t *testing.T) {
	logger := observability.NewNoOpLogger()
	wcChan := make(chan tea.Msg, 10)

	hm := leet.NewHeartbeatManager(50*time.Millisecond, wcChan, logger)

	isRunning := func() bool { return false }
	hm.Start(isRunning)

	select {
	case <-wcChan:
		t.Fatal("heartbeat sent when run not active")
	case <-time.After(150 * time.Millisecond):
		// Expected - no heartbeat
	}
}

func TestHeartbeatManager_StopsProperly(t *testing.T) {
	logger := observability.NewNoOpLogger()
	wcChan := make(chan tea.Msg, 10)

	hm := leet.NewHeartbeatManager(100*time.Millisecond, wcChan, logger)

	isRunning := func() bool { return true }
	hm.Start(isRunning)
	hm.Stop()

	select {
	case <-wcChan:
		t.Fatal("heartbeat sent after Stop")
	case <-time.After(200 * time.Millisecond):
		// Expected - no heartbeat after stop
	}
}

func TestHeartbeatManager_ResetRestartsTimer(t *testing.T) {
	logger := observability.NewNoOpLogger()
	wcChan := make(chan tea.Msg, 10)

	hm := leet.NewHeartbeatManager(100*time.Millisecond, wcChan, logger)

	isRunning := func() bool { return true }
	hm.Start(isRunning)

	// Wait almost until heartbeat
	time.Sleep(80 * time.Millisecond)
	hm.Reset(isRunning)

	// Original heartbeat shouldn't fire
	time.Sleep(40 * time.Millisecond)
	select {
	case <-wcChan:
		t.Fatal("original heartbeat fired after reset")
	default:
		// Expected
	}

	// New heartbeat should fire after full interval from reset
	select {
	case msg := <-wcChan:
		_, ok := msg.(leet.HeartbeatMsg)
		require.True(t, ok)
	case <-time.After(100 * time.Millisecond):
		t.Fatal("heartbeat not received after reset")
	}

	hm.Stop()
}

func TestHeartbeatManager_ChecksIsRunningBeforeSending(t *testing.T) {
	logger := observability.NewNoOpLogger()
	wcChan := make(chan tea.Msg, 10)

	hm := leet.NewHeartbeatManager(100*time.Millisecond, wcChan, logger)

	var running atomic.Bool
	running.Store(true)

	hm.Start(running.Load)

	// Stop the run before heartbeat fires
	time.Sleep(50 * time.Millisecond)
	running.Store(false)

	// Wait for when heartbeat would fire
	time.Sleep(100 * time.Millisecond)

	// Should not receive heartbeat
	select {
	case <-wcChan:
		t.Fatal("heartbeat sent after run stopped")
	default:
		// Expected
	}

	hm.Stop()
}

func TestHeartbeatManager_MultipleStartsAndResets(t *testing.T) {
	logger := observability.NewNoOpLogger()
	wcChan := make(chan tea.Msg, 10)

	hm := leet.NewHeartbeatManager(50*time.Millisecond, wcChan, logger)

	isRunning := func() bool { return true }

	hm.Start(isRunning)
	hm.Reset(isRunning)
	hm.Start(isRunning)
	hm.Reset(isRunning)

	// Should get exactly one heartbeat after the interval
	timeout := time.After(150 * time.Millisecond)
	msgCount := 0

	for {
		select {
		case <-wcChan:
			msgCount++
		case <-timeout:
			require.Equal(t, 1, msgCount, "expected exactly one heartbeat")
			hm.Stop()
			return
		}
	}
}
