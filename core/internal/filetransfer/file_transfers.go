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
	GCSReference FileTransfer
}

// NewFileTransfers creates a new fileTransfers
func NewFileTransfers(
	client *retryablehttp.Client,
	logger *observability.CoreLogger,
	fileTransferStats FileTransferStats,
) *FileTransfers {
	defaultFileTransfer := NewDefaultFileTransfer(client, logger, fileTransferStats)
	gcReferenceFileTransfer := NewGCSFileTransfer(nil, logger, fileTransferStats)
	return &FileTransfers{
		Default:      defaultFileTransfer,
		GCSReference: gcReferenceFileTransfer,
	}
}

// Returns the appropriate fileTransfer depending on task
func (ft *FileTransfers) GetFileTransferForTask(task *Task) FileTransfer {
	switch {
	case ft.GCSReference.CanHandle(task):
		return ft.GCSReference
	default:
		return ft.Default
	}
}
