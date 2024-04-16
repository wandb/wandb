// Package watcher2 defines a file watcher.
//
// It is the successor to "watcher", which will eventually be removed.
package watcher2

import (
	"time"

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
	//
	// The file must exist, or an error is returned.
	Watch(path string, onChange func()) error

	// Finish stops the watcher from emitting any more change events.
	Finish()
}

type Params struct {
	Logger *observability.CoreLogger

	// How often to poll files for updates.
	//
	// If unset, this uses a default value.
	PollingPeriod time.Duration
}

func New(params Params) Watcher {
	return newWatcher(params)
}
