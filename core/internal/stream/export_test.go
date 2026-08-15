package stream

import (
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/runhandle"
)

// SetFileStreamForTest injects a FileStream implementation for stream_test.
func (s *Sender) SetFileStreamForTest(fs filestream.FileStream) {
	s.fileStream = fs
}

// SetRunHandleForTest replaces the run handle for stream_test.
func (s *Sender) SetRunHandleForTest(rh *runhandle.RunHandle) {
	s.runHandle = rh
}
