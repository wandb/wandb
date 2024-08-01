package filetransfer

import (
	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/pkg/observability"
)

type FileTransfer interface {
	CanHandle(task *Task) bool
	Upload(task *Task) error
	Download(task *Task) error
}

// FileTransfers is a collection of file transfers by upload destination type.
type FileTransfers struct {
	// Default makes an HTTP request to the destination URL with the file contents.
	Default      FileTransfer
	GCS FileTransfer
}

// NewFileTransfers creates a new fileTransfers
func NewFileTransfers(
	client *retryablehttp.Client,
	logger *observability.CoreLogger,
	fileTransferStats FileTransferStats,
) *FileTransfers {
	defaultFileTransfer := NewDefaultFileTransfer(client, logger, fileTransferStats)
	gcsFileTransfer := NewGCSFileTransfer(nil, logger, fileTransferStats)
	return &FileTransfers{
		Default:      defaultFileTransfer,
		GCS: gcsFileTransfer,
	}
}

// Returns the appropriate fileTransfer depending on task
func (ft *FileTransfers) GetFileTransferForTask(task *Task) FileTransfer {
	switch {
	case ft.GCS.CanHandle(task):
		return ft.GCS
	default:
		return ft.Default
	}
}
