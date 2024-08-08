package filestreamtest

import (
	"slices"
	"sync"

	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/pkg/observability"
)

// A fake implementation of FileStream.
type FakeFileStream struct {
	sync.Mutex
	updates []filestream.Update
}

func NewFakeFileStream() *FakeFileStream {
	return &FakeFileStream{
		updates: make([]filestream.Update, 0),
	}
}

// GetUpdates returns all updates passed to `StreamUpdate`.
func (fs *FakeFileStream) GetUpdates() []filestream.Update {
	fs.Lock()
	defer fs.Unlock()
	return slices.Clone(fs.updates)
}

// GetRequest returns a request accumulated from applying all updates.
func (fs *FakeFileStream) GetRequest(
	settings *settings.Settings,
) *filestream.FileStreamRequest {
	fullRequest := &filestream.FileStreamRequest{}

	for _, update := range fs.GetUpdates() {
		_ = update.Apply(filestream.UpdateContext{
			MakeRequest: func(request *filestream.FileStreamRequest) {
				fullRequest.Merge(request)
			},

			Settings: settings,
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

func (fs *FakeFileStream) FinishWithExit(int32) {}
func (fs *FakeFileStream) FinishWithoutExit()   {}

func (fs *FakeFileStream) StreamUpdate(update filestream.Update) {
	fs.Lock()
	defer fs.Unlock()

	fs.updates = append(fs.updates, update)
}
