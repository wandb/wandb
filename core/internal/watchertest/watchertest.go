// Package watchertest defines a fake Watcher implementation for testing.
package watchertest

import (
	"os"
	"path/filepath"
	"sync"

	"github.com/wandb/wandb/core/internal/watcher"
)

// FakeWatcher is a Watcher implementation that can be used in tests.
type FakeWatcher struct {
	mu sync.Mutex

	handlers map[string]func(string)
}

var _ watcher.Watcher = &FakeWatcher{}

func NewFakeWatcher() *FakeWatcher {
	return &FakeWatcher{
		handlers: make(map[string]func(string)),
	}
}

// OnChange invokes the change callback registered for the path, if any.
func (w *FakeWatcher) OnChange(path string) {
	w.mu.Lock()
	handler := w.handlers[path]
	parentHandler := w.handlers[filepath.Dir(path)]
	w.mu.Unlock()

	if handler != nil {
		handler(path)
	} else if parentHandler != nil {
		parentHandler(path)
	}
}

// IsWatching reports whether a callback is registered for the path.
func (w *FakeWatcher) IsWatching(path string) bool {
	w.mu.Lock()
	defer w.mu.Unlock()

	return w.handlers[w.toAbs(path)] != nil
}

func (w *FakeWatcher) Watch(path string, callback func()) error {
	return w.watchFileOrDir(path, func(string) { callback() })
}

func (w *FakeWatcher) WatchDir(path string, callback func(string)) error {
	return w.watchFileOrDir(path, callback)
}

func (w *FakeWatcher) watchFileOrDir(path string, callback func(string)) error {
	w.mu.Lock()
	defer w.mu.Unlock()

	// Raise an error for non-existent paths like the real implementation.
	_, err := os.Stat(path)
	if err != nil {
		return err
	}

	w.handlers[w.toAbs(path)] = callback
	return nil
}

func (w *FakeWatcher) toAbs(path string) string {
	absPath, err := filepath.Abs(path)

	if err != nil {
		panic(err)
	}

	return absPath
}

func (w *FakeWatcher) Finish() {}
