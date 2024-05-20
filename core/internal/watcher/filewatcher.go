package watcher

import (
	"os"
	"sync"

	"github.com/wandb/wandb/core/internal/waiting"
)

// fileWatcher detects modifications to a single file.
//
// If the file is a symlink, this tracks modifications to the target of the
// symlink rather than the symlink itself.
type fileWatcher struct {
	sync.Mutex

	// wg is a wait group that's done when the polling loop exits.
	wg sync.WaitGroup

	// cancelChan is a channel that's closed when the watcher should stop.
	cancelChan chan struct{}

	// lastExisted is whether the file existed last we checked.
	lastExisted bool

	// lastModToken is the file's status last we checked, if it existed.
	lastModToken FileModToken

	// absPath is a normalized path to the file being watched.
	absPath string

	// pollingStopwatch is how frequently to poll the file.
	pollingStopwatch waiting.Stopwatch

	// callbacks is a list of callbacks to invoke when the file changes.
	callbacks []func()
}

func NewFileWatcher(
	absPath string,
	pollingStopwatch waiting.Stopwatch,
) *fileWatcher {
	return &fileWatcher{
		cancelChan:       make(chan struct{}),
		absPath:          absPath,
		pollingStopwatch: pollingStopwatch,
		callbacks:        make([]func(), 0),
	}
}

// AddCallback registers a callback to run when the file is modified.
//
// The callback is invoked when the file changes, is deleted, or is created.
func (w *fileWatcher) AddCallback(cb func()) {
	w.Lock()
	defer w.Unlock()

	// stat first to guarantee:
	//  1. cb is not invoked for modifications before AddCallback
	//  2. cb is invoked for modifications after AddCallback
	w.stat()

	w.callbacks = append(w.callbacks, cb)
}

// Start begins polling the file periodically.
//
// It must only be called once.
func (w *fileWatcher) Start() {
	w.wg.Add(1)
	go func() {
		defer w.wg.Done()

		for {
			select {
			case <-w.pollingStopwatch.Wait():
				// pass
			case <-w.cancelChan:
				return
			}

			w.Lock()
			w.stat()
			w.Unlock()
		}
	}()
}

// Stop makes the watcher stop polling the file.
//
// It must only be called once, after Start().
func (w *fileWatcher) Stop() {
	close(w.cancelChan)

	// Forget all callbacks.
	w.Lock()
	w.callbacks = make([]func(), 0)
	w.Unlock()

	w.wg.Wait()
}

// stat checks the file and invokes callbacks if it was modified.
//
// The mutex must be held.
func (w *fileWatcher) stat() {
	w.pollingStopwatch.Reset()
	info, err := os.Stat(w.absPath)

	var nextExisted bool
	var nextModToken FileModToken
	defer func() {
		w.lastExisted = nextExisted
		w.lastModToken = nextModToken
	}()

	if err != nil || info.IsDir() {
		nextExisted = false
		nextModToken = FileModToken{}
	} else {
		nextExisted = true
		nextModToken = FileModTokenFrom(info)
	}

	if nextExisted != w.lastExisted || nextModToken != w.lastModToken {
		// Invoke all callbacks in parallel.
		wg := &sync.WaitGroup{}
		for _, cb := range w.callbacks {
			wg.Add(1)
			go func() {
				cb()
				wg.Done()
			}()
		}
		wg.Wait()
	}
}
