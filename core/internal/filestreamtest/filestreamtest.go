package filestreamtest

import (
	"slices"
	"sync"

	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/settings"
)

// A fake implementation of FileStream.
type FakeFileStream struct {
	mu      sync.Mutex
	updates []filestream.Update
}

func NewFakeFileStream() *FakeFileStream {
	return &FakeFileStream{
		updates: make([]filestream.Update, 0),
	}
}

// GetUpdates returns all updates passed to `StreamUpdate`.
func (fs *FakeFileStream) GetUpdates() []filestream.Update {
	fs.mu.Lock()
	defer fs.mu.Unlock()
	return slices.Clone(fs.updates)
}

// GetRequest returns a request accumulated from applying all updates.
func (fs *FakeFileStream) GetRequest(
	s *settings.Settings,
) *filestream.FileStreamRequest {
	fullRequest := &filestream.FileStreamRequest{}

	for _, update := range fs.GetUpdates() {
		_ = update.Apply(filestream.UpdateContext{
			MakeRequest: func(request *filestream.FileStreamRequest) {
				fullRequest.Merge(request)
			},

			Settings: s,
			Logger:   observability.NewNoOpLogger(),
			Printer:  observability.NewPrinter(),
		})
	}

	return fullRequest
}

// Prove that we implement the interface.
var _ filestream.FileStream = &FakeFileStream{}

func (fs *FakeFileStream) Start(
	entity string,
	project string,
	runID string,
	offsetMap filestream.FileStreamOffsetMap,
) {
}

func (fs *FakeFileStream) FinishWithExit(int32, bool) {}
func (fs *FakeFileStream) FinishWithoutExit()   {}

func (fs *FakeFileStream) StreamUpdate(update filestream.Update) {
	fs.mu.Lock()
	defer fs.mu.Unlock()

	fs.updates = append(fs.updates, update)
}

func (fs *FakeFileStream) IsStopped() bool {
	return false
}
