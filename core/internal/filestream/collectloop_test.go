package filestream_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/filestream"
)

type uploadedFilesUpdate struct {
	file string
}

func (s *uploadedFilesUpdate) Apply(state *filestream.CollectorState) {
	state.UploadedFiles = append(state.UploadedFiles, s.file)
}

func TestCollectLoop_BatchesWhileWaiting(t *testing.T) {
	updates := make(chan filestream.CollectorStateUpdate)
	defer close(updates)
	loop := filestream.CollectLoop{}

	transmissions := loop.Start(updates, filestream.FileStreamOffsetMap{})
	updates <- &uploadedFilesUpdate{file: "one"}
	updates <- &uploadedFilesUpdate{file: "two"}
	updates <- &uploadedFilesUpdate{file: "three"}

	select {
	case result := <-transmissions:
		assert.Equal(t,
			[]string{"one", "two", "three"},
			result.Uploaded)
	case <-time.After(time.Second):
		t.Error("timeout after 1 second")
	}
}
