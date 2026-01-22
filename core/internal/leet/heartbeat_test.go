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
	outChan := make(chan tea.Msg, 10)

	hm := leet.NewHeartbeatManager(100*time.Millisecond, outChan, logger)

	isRunning := func() bool { return true }
	hm.Start(isRunning)

	select {
	case msg := <-outChan:
		_, ok := msg.(leet.HeartbeatMsg)
		require.True(t, ok, "expected HeartbeatMsg")
	case <-time.After(200 * time.Millisecond):
		t.Fatal("heartbeat not received within timeout")
	}

	hm.Stop()
}

func TestHeartbeatManager_DoesNotStartWhenNotRunning(t *testing.T) {
	logger := observability.NewNoOpLogger()
	outChan := make(chan tea.Msg, 10)

	hm := leet.NewHeartbeatManager(50*time.Millisecond, outChan, logger)

	isRunning := func() bool { return false }
	hm.Start(isRunning)

	select {
	case <-outChan:
		t.Fatal("heartbeat sent when run not active")
	case <-time.After(150 * time.Millisecond):
		// Expected - no heartbeat
	}
}

func TestHeartbeatManager_StopsProperly(t *testing.T) {
	logger := observability.NewNoOpLogger()
	outChan := make(chan tea.Msg, 10)

	hm := leet.NewHeartbeatManager(100*time.Millisecond, outChan, logger)

	isRunning := func() bool { return true }
	hm.Start(isRunning)
	hm.Stop()

	select {
	case <-outChan:
		t.Fatal("heartbeat sent after Stop")
	case <-time.After(200 * time.Millisecond):
		// Expected - no heartbeat after stop
	}
}

func TestHeartbeatManager_ResetRestartsTimer(t *testing.T) {
	logger := observability.NewNoOpLogger()
	outChan := make(chan tea.Msg, 10)

	const interval = 100 * time.Millisecond
	hm := leet.NewHeartbeatManager(interval, outChan, logger)

	isRunning := func() bool { return true }
	hm.Start(isRunning)

	// Wait for a bit, but not too close to the interval boundary.
	time.Sleep(interval / 2)
	hm.Reset(isRunning)

	// Original heartbeat shouldn't fire shortly after reset.
	time.Sleep(interval / 3)
	select {
	case <-outChan:
		t.Fatal("original heartbeat fired after reset")
	default:
		// Expected
	}

	// New heartbeat should fire after the full interval from reset.
	select {
	case msg := <-outChan:
		_, ok := msg.(leet.HeartbeatMsg)
		require.True(t, ok)
	case <-time.After(interval):
		t.Fatal("heartbeat not received after reset")
	}

	hm.Stop()
}

func TestHeartbeatManager_ChecksIsRunningBeforeSending(t *testing.T) {
	logger := observability.NewNoOpLogger()
	outChan := make(chan tea.Msg, 10)

	hm := leet.NewHeartbeatManager(100*time.Millisecond, outChan, logger)

	var running atomic.Bool
	running.Store(true)

	hm.Start(running.Load)

	// Stop the run before heartbeat fires.
	time.Sleep(50 * time.Millisecond)
	running.Store(false)

	// Wait for when heartbeat would fire.
	time.Sleep(100 * time.Millisecond)

	// Should not receive heartbeat.
	select {
	case <-outChan:
		t.Fatal("heartbeat sent after run stopped")
	default:
		// Expected
	}

	hm.Stop()
}

func TestHeartbeatManager_MultipleStartsAndResets(t *testing.T) {
	logger := observability.NewNoOpLogger()
	outChan := make(chan tea.Msg, 10)

	hm := leet.NewHeartbeatManager(50*time.Millisecond, outChan, logger)

	isRunning := func() bool { return true }

	hm.Start(isRunning)
	hm.Reset(isRunning)
	hm.Start(isRunning)
	hm.Reset(isRunning)

	// Should get exactly one heartbeat after the interval.
	timeout := time.After(150 * time.Millisecond)
	msgCount := 0

	for {
		select {
		case <-outChan:
			msgCount++
		case <-timeout:
			require.Equal(t, 1, msgCount, "expected exactly one heartbeat")
			hm.Stop()
			return
		}
	}
}
