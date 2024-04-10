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
	// `onChange` is invoked whenever the contents of the file change.
	//
	// The file must exist, or an error is returned.
	//
	// NOTE: If the file is deleted later, it is still watched,
	// and the callback is invoked when it is created. Do not rely on
	// this behavior---it is a workaround for a race condition in the
	// library we use.
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
