package watcher

import (
	"io/fs"
	"os"
	"path/filepath"
	"sync"

	"github.com/wandb/wandb/core/internal/waiting"
)

// treeWatcher detects modifications in a directory tree.
//
// It does not follow symlinks, but it does check symlink targets for
// modifications.
type treeWatcher struct {
	sync.Mutex

	// wg is a wait group that's done when the polling loop exits.
	wg sync.WaitGroup

	// cancelChan is a channel that's closed when the watcher should stop.
	cancelChan chan struct{}

	// lastModToken is the last status of every file under the directory.
	lastModToken map[string]FileModToken

	// absRootPath is a normalized path to the directory being watched.
	absRootPath string

	// pollingStopwatch is how frequently to poll the directory.
	pollingStopwatch waiting.Stopwatch

	// callbacks is a list of callbacks to invoke when the directory changes.
	callbacks []func(string)
}

func NewTreeWatcher(
	absPath string,
	pollingStopwatch waiting.Stopwatch,
) *treeWatcher {
	return &treeWatcher{
		cancelChan:       make(chan struct{}),
		lastModToken:     make(map[string]FileModToken),
		absRootPath:      absPath,
		pollingStopwatch: pollingStopwatch,
		callbacks:        make([]func(string), 0),
	}
}

// AddCallback registers a callback to run when the directory is modified.
//
// The callback is invoked with the path of any file under the directory
// that changes, is deleted, or is created.
func (w *treeWatcher) AddCallback(cb func(string)) {
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
func (w *treeWatcher) Start() {
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
func (w *treeWatcher) Stop() {
	close(w.cancelChan)

	// Forget all callbacks.
	w.Lock()
	w.callbacks = make([]func(string), 0)
	w.Unlock()

	w.wg.Wait()
}

// stat walks the directory and invokes callbacks if it was modified.
//
// The mutex must be held. Note that this could take arbitrarily long
// depending on the size of the directory tree, meaning that the mutex would
// be held for all that time. That is unavoidable---however, this method is
// designed to exit early if Stop() is invoked.
func (w *treeWatcher) stat() {
	w.pollingStopwatch.Reset()

	nextModToken := make(map[string]FileModToken)
	defer func() {
		w.lastModToken = nextModToken
	}()

	_ = filepath.WalkDir(w.absRootPath, func(path string, d fs.DirEntry, err error) error {
		// Check if we should stop.
		select {
		case <-w.cancelChan:
			return filepath.SkipAll
		default:
		}

		// Don't invoke callbacks if there's an error, or if this is
		// a directory, or if this is the root path.
		//
		// d can be nil, but supposedly only when path is the root.
		// It's not obvious from the docs, so check to be safe.
		if path == w.absRootPath ||
			err != nil ||
			d == nil ||
			d.IsDir() {
			return nil
		}

		// We use Stat() here so that if the file is a symbolic link, we're
		// examining its target.
		var info os.FileInfo
		info, err = os.Stat(path)
		if err != nil || info.IsDir() {
			return nil
		}

		// NOTE: 'path' should be normalized (i.e. clean & absolute) because
		// it's prefixed by the root which is normalized, and we assume that
		// WalkDir() doesn't insert unnecessary slashes or dots.
		nextModToken[path] = FileModTokenFrom(info)

		return nil
	})

	modified := make(map[string]struct{})

	// Detect changed and created files.
	for path, newToken := range nextModToken {
		oldToken, existed := w.lastModToken[path]

		if !existed || newToken != oldToken {
			modified[path] = struct{}{}
		}

		delete(w.lastModToken, path)
	}

	// Detect deleted files.
	for path := range w.lastModToken {
		modified[path] = struct{}{}
	}

	// Invoke all callbacks in parallel.
	wg := &sync.WaitGroup{}
	for _, cb := range w.callbacks {
		for path := range modified {
			cb := cb
			path := path

			wg.Add(1)
			go func() {
				defer wg.Done()
				cb(path)
			}()
		}
	}
	wg.Wait()
}
