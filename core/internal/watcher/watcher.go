// Package watcher notifies on changes to files or directories.
package watcher

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

	// WatchDir begins watching the contents of the directory at the path.
	//
	// `onChange` is invoked with a file path if a direct child of the
	// directory is changed or created. The directory is not watched
	// recursively.
	//
	// The directory must exist, or an error is returned.
	WatchDir(path string, onChange func(string)) error

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
