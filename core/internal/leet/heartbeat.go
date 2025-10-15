package leet

import (
	"fmt"
	"sync"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/wandb/wandb/core/internal/observability"
)

// HeartbeatManager manages periodic heartbeat messages for live runs.
type HeartbeatManager struct {
	timer    *time.Timer
	interval time.Duration
	mu       sync.Mutex
	logger   *observability.CoreLogger
	wcChan   chan tea.Msg
}

func NewHeartbeatManager(
	interval time.Duration,
	wcChan chan tea.Msg,
	logger *observability.CoreLogger,
) *HeartbeatManager {
	return &HeartbeatManager{
		interval: interval,
		wcChan:   wcChan,
		logger:   logger,
	}
}

// Start starts the heartbeat timer.
func (hm *HeartbeatManager) Start(isRunning func() bool) {
	hm.mu.Lock()
	defer hm.mu.Unlock()

	// Stop any existing timer
	if hm.timer != nil {
		hm.timer.Stop()
	}

	if !isRunning() {
		hm.logger.Debug("heartbeat: not starting - run not active")
		return
	}

	hm.logger.Debug(fmt.Sprintf("heartbeat: starting with interval %v", hm.interval))

	hm.timer = time.AfterFunc(hm.interval, func() {
		if !isRunning() {
			return
		}

		select {
		case hm.wcChan <- HeartbeatMsg{}:
			hm.logger.Debug("heartbeat: triggered")
		default:
			hm.logger.Warn("heartbeat: wcChan full, dropping message")
		}
	})
}

// Reset resets the heartbeat timer.
func (hm *HeartbeatManager) Reset(isRunning func() bool) {
	hm.mu.Lock()
	defer hm.mu.Unlock()

	// Stop existing timer
	if hm.timer != nil {
		hm.timer.Stop()
	}

	if !isRunning() {
		return
	}

	hm.logger.Debug("heartbeat: resetting timer")

	hm.timer = time.AfterFunc(hm.interval, func() {
		if !isRunning() {
			return
		}

		select {
		case hm.wcChan <- HeartbeatMsg{}:
			hm.logger.Debug("heartbeat: triggered after reset")
		default:
			hm.logger.Warn("heartbeat: wcChan full, dropping message after reset")
		}
	})
}

// Stop stops the heartbeat timer.
func (hm *HeartbeatManager) Stop() {
	hm.mu.Lock()
	defer hm.mu.Unlock()

	if hm.timer != nil {
		hm.timer.Stop()
		hm.timer = nil
		hm.logger.Debug("heartbeat: stopped")
	}
}
