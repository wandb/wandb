// Package watcher notifies on changes to files or directories.
package watcher

import (
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/pkg/observability"
)

// Watcher invokes callbacks when registered files are modified.
type Watcher interface {
	// Watch begins watching the file at the specified path.
	//
	// `onChange` is **usually** invoked after the contents of the file may
	// have changed.
	//
	// In some cases, like if the file is modified too quickly, `onChange` may
	// not run because the file's mtime is unchanged. There is no guarantee
	// that `onChange` will be invoked after the final change to a file!
	Watch(path string, onChange func()) error

	// WatchTree begins recursively watching the file tree rooted at the path.
	//
	// `onChange` is invoked with a file path if any child of the directory is
	// changed, created or deleted. It is not invoked if the path itself refers
	// to a file.
	WatchTree(path string, onChange func(string)) error

	// Finish stops the watcher from emitting any more change events.
	Finish()
}

// WatcherTesting has additional test-only methods.
type WatcherTesting interface {
	// StatAllNow polls all watched files immediately.
	StatAllNow()
}

type Params struct {
	Logger *observability.CoreLogger

	// PollingStopwatch is how often to poll files for updates.
	//
	// If unset, this uses a default value.
	PollingStopwatch waiting.StopwatchFactory
}

func New(params Params) Watcher {
	return newWatcher(params)
}
