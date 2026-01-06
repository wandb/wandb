package leet

import (
	"fmt"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/watcher"
)

// WatcherManager manages file watching for live runs.
type WatcherManager struct {
	watcher watcher.Watcher
	started bool
	outChan chan tea.Msg
	logger  *observability.CoreLogger
}

// NewWatcherManager creates a new watcher manager.
func NewWatcherManager(
	outChan chan tea.Msg,
	logger *observability.CoreLogger,
) *WatcherManager {
	return &WatcherManager{
		watcher: watcher.New(watcher.Params{Logger: logger}),
		outChan: outChan,
		logger:  logger,
	}
}

// Start starts watching the specified file.
func (wm *WatcherManager) Start(runPath string) error {
	if wm.started {
		return nil
	}

	wm.logger.Debug(fmt.Sprintf("watcher: starting for path: %s", runPath))

	err := wm.watcher.Watch(runPath, func() {
		wm.logger.Debug(fmt.Sprintf("watcher: file changed: %s", runPath))

		select {
		case wm.outChan <- FileChangedMsg{}:
			wm.logger.Debug("watcher: FileChangedMsg sent")
		default:
			wm.logger.CaptureWarn("watcher: outChan full, dropping FileChangedMsg")
		}
	})

	if err != nil {
		wm.logger.CaptureError(fmt.Errorf("watcher: error starting: %v", err))
		return err
	}

	wm.started = true
	wm.logger.Debug("watcher: started successfully")
	return nil
}

// Finish stops the watcher.
func (wm *WatcherManager) Finish() {
	if !wm.started {
		return
	}

	wm.logger.Debug("watcher: finishing")
	wm.watcher.Finish()
	wm.started = false

	// Unblock any pending WaitForMsg calls.
	select {
	case wm.outChan <- nil:
	default:
	}
}

// IsStarted returns whether the watcher is started.
func (wm *WatcherManager) IsStarted() bool {
	return wm.started
}

// WaitForMsg waits for watcher messages.
func (wm *WatcherManager) WaitForMsg() tea.Msg {
	wm.logger.Debug("watcher: waiting for message...")
	msg := <-wm.outChan
	if msg != nil {
		wm.logger.Debug(fmt.Sprintf("watcher: received message: %T", msg))
	}
	return msg
}
