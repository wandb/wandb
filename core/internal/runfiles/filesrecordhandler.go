package runfiles

import (
	"sync"
	"sync/atomic"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

// Internal implementation of the FilesRecordHandler interface.
type handler struct {
	logger       *observability.CoreLogger
	settings     *settings.Settings
	fileTransfer filetransfer.FileTransferManager
	graphQL      graphql.Client

	// Wait group for file uploads.
	uploadWg *sync.WaitGroup

	// Set of files (not directories) to upload later.
	flushSet map[string]FileInfo

	// Whether 'Finish' was called.
	isFinished *atomic.Bool

	// Mutex that's locked whenever any state is being read or modified.
	stateMu *sync.Mutex
}

func newFilesRecordHandler(params FilesRecordHandlerParams) FilesRecordHandler {
	return &handler{
		logger:       params.Logger,
		settings:     params.Settings,
		fileTransfer: params.FileTransfer,
		graphQL:      params.GraphQL,

		uploadWg: &sync.WaitGroup{},

		flushSet: make(map[string]FileInfo),

		isFinished: &atomic.Bool{},

		stateMu: &sync.Mutex{},
	}
}

func (h *handler) ProcessRecord(record *service.FilesRecord) {
	if h.isFinished.Load() {
		h.logger.CaptureError("runfiles: called ProcessRecord() after Finish()", nil)
		return
	}

	h.stateMu.Lock()
	defer h.stateMu.Unlock()
	// TODO
}

func (h *handler) Flush() {
	if h.isFinished.Load() {
		h.logger.CaptureError("runfiles: called Flush() after Finish()", nil)
		return
	}

	h.stateMu.Lock()
	defer h.stateMu.Unlock()

	for path, info := range h.flushSet {
		// Avoid capturing the loop variables.
		path := path
		info := info

		h.uploadWg.Add(1)
		go func() {
			h.uploadFile(path, info)
			h.uploadWg.Done()
		}()
	}
}

func (h *handler) Finish() {
	// Mark as finished. Do nothing if already finished.
	if h.isFinished.Swap(true) {
		return
	}

	h.stateMu.Lock()
	defer h.stateMu.Unlock()

	h.uploadWg.Wait()
}

func (h *handler) uploadFile(path string, info FileInfo) {
	// TODO
}
