package filestreamtest

import (
	"slices"
	"sync"

	"github.com/wandb/wandb/core/pkg/filestream"
	"github.com/wandb/wandb/core/pkg/service"
)

// A fake implementation of FileStream.
type FakeFileStream struct {
	sync.Mutex

	records       []*service.Record
	filesUploaded []string
}

func NewFakeFileStream() *FakeFileStream {
	return &FakeFileStream{
		records:       make([]*service.Record, 0),
		filesUploaded: make([]string, 0),
	}
}

// Returns all records passed to `StreamRecord`.
func (fs *FakeFileStream) GetRecords() []*service.Record {
	fs.Lock()
	defer fs.Unlock()
	return slices.Clone(fs.records)
}

// GetFilesUploaded returns all invocations of `SignalFileUploaded`.
func (fs *FakeFileStream) GetFilesUploaded() []string {
	fs.Lock()
	defer fs.Unlock()
	return slices.Clone(fs.filesUploaded)
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

func (fs *FakeFileStream) Close() {}

func (fs *FakeFileStream) StreamRecord(rec *service.Record) {
	fs.Lock()
	defer fs.Unlock()

	fs.records = append(fs.records, rec)
}

func (fs *FakeFileStream) SignalFileUploaded(path string) {
	fs.Lock()
	defer fs.Unlock()

	fs.filesUploaded = append(fs.filesUploaded, path)
}
