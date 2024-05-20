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

	// rootCallbacks is a list of callbacks to invoke when the file at the root
	// of the tree changes.
	rootCallbacks []func()

	// childCallbacks is a list of callbacks to invoke when the directory changes.
	childCallbacks []func(string)
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
		rootCallbacks:    make([]func(), 0),
		childCallbacks:   make([]func(string), 0),
	}
}

// AddRootCallback registers a callback to run when the root file changes.
//
// The callback is invoked when the file pointed to by the root path
// is modified, is deleted, or is created. If the path changes from
// being a file to being a directory, that counts as deleting the file,
// and vice versa is creating the file.
func (w *treeWatcher) AddRootCallback(cb func()) {
	w.Lock()
	defer w.Unlock()

	w.stat()

	w.rootCallbacks = append(w.rootCallbacks, cb)
}

// AddChildCallback registers a callback to run when the directory is modified.
//
// The callback is invoked with the path of any file under the directory
// that changes, is deleted, or is created.
func (w *treeWatcher) AddChildCallback(cb func(string)) {
	w.Lock()
	defer w.Unlock()

	w.stat()

	w.childCallbacks = append(w.childCallbacks, cb)
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
				// keep looping
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
	w.rootCallbacks = make([]func(), 0)
	w.childCallbacks = make([]func(string), 0)
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
		// Stop walking if the watcher is stopped.
		select {
		case <-w.cancelChan:
			return filepath.SkipAll
		default:
		}

		// Don't invoke callbacks if there's an error or if this is a directory.
		//
		// d can be nil when path is the root.
		if err != nil ||
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

		// If we only care about the root file, stop walking.
		if len(w.childCallbacks) == 0 {
			return filepath.SkipAll
		}

		return nil
	})

	// If the watcher was stopped, don't do anything more.
	select {
	case <-w.cancelChan:
		return
	default:
	}

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
	for path := range modified {
		if path == w.absRootPath {
			for _, cb := range w.rootCallbacks {
				cb := cb

				wg.Add(1)
				go func() {
					defer wg.Done()
					cb()
				}()
			}
		} else {
			for _, cb := range w.childCallbacks {
				cb := cb
				path := path

				wg.Add(1)
				go func() {
					defer wg.Done()
					cb(path)
				}()
			}
		}
	}
	wg.Wait()
}
