// heartbeat.go
package leet

import (
	"fmt"
	"sync"
	"sync/atomic"
	"time"

	tea "charm.land/bubbletea/v2"

	"github.com/wandb/wandb/core/internal/observability"
)

// RunCrashTimeout is how long a live run may go without writing to its
// transaction log before LEET presumes it crashed.
//
// Modeled on the server's stale-runs sweep (staleRunHeartbeatThreshold in
// gorilla), which moves running runs with no filestream heartbeat for
// 5 minutes to the crashed state. Locally, writes to the .wandb file play
// the role of the heartbeat, and their cadence varies more than the SDK's
// heartbeats, so be twice as lenient.
const RunCrashTimeout = 10 * time.Minute

// HeartbeatManager manages periodic heartbeat messages for live runs.
type HeartbeatManager struct {
	mu         sync.Mutex // guards timer lifecycle (start/stop/replace)
	timer      *time.Timer
	interval   time.Duration
	logger     *observability.CoreLogger
	outChan    chan tea.Msg
	generation atomic.Uint64 // increments on each (re)arm/stop; stale callbacks bail out
}

func NewHeartbeatManager(
	interval time.Duration,
	outChan chan tea.Msg,
	logger *observability.CoreLogger,
) *HeartbeatManager {
	return &HeartbeatManager{
		interval: interval,
		outChan:  outChan,
		logger:   logger,
	}
}

// arm arms the timer for the current interval using the provided generation.
//
// The caller must hold hm.mu.
// isRunning is called from the timer goroutine and must be safe for concurrent use.
func (hm *HeartbeatManager) arm(gen uint64, isRunning func() bool) {
	hm.timer = time.AfterFunc(hm.interval, func() {
		// Discard stale callbacks (racing AfterFunc from a previous reset/start/stop).
		if hm.generation.Load() != gen || !isRunning() {
			return
		}

		select {
		case hm.outChan <- HeartbeatMsg{}:
			hm.logger.Debug("heartbeat: triggered")
		default:
			hm.logger.Warn("heartbeat: outChan full, dropping message")
		}
	})
}

// Start starts the heartbeat timer.
//
// isRunning is called both synchronously (to gate arming) and later from
// the timer goroutine (to gate sending). It must be safe for concurrent use
// (e.g., an atomic.Bool.Load or other goroutine-safe function).
func (hm *HeartbeatManager) Start(isRunning func() bool) {
	hm.mu.Lock()
	defer hm.mu.Unlock()

	// Invalidate all in-flight callbacks *before* stopping/arming.
	gen := hm.generation.Add(1)

	// Stop any existing timer (best effort).
	if hm.timer != nil {
		hm.timer.Stop()
	}

	if !isRunning() {
		hm.logger.Debug("heartbeat: not starting - run not active")
		return
	}

	hm.logger.Debug(fmt.Sprintf("heartbeat: starting with interval %v", hm.interval))
	hm.arm(gen, isRunning)
}

// Reset resets the heartbeat timer.
//
// isRunning has the same concurrency requirements as in Start.
func (hm *HeartbeatManager) Reset(isRunning func() bool) {
	hm.mu.Lock()
	defer hm.mu.Unlock()

	// Invalidate callbacks from the prior arming.
	gen := hm.generation.Add(1)

	// Stop the previous timer (best effort).
	if hm.timer != nil {
		hm.timer.Stop()
	}

	if !isRunning() {
		return
	}

	hm.logger.Debug("heartbeat: resetting timer")
	hm.arm(gen, isRunning)
}

// Stop stops the heartbeat timer.
func (hm *HeartbeatManager) Stop() {
	hm.mu.Lock()
	defer hm.mu.Unlock()

	// Invalidate all in-flight callbacks before stopping the timer.
	hm.generation.Add(1)

	if hm.timer != nil {
		hm.timer.Stop()
		hm.timer = nil
		hm.logger.Debug("heartbeat: stopped")
	} else {
		hm.logger.Debug("heartbeat: stopped (no timer)")
	}
}
