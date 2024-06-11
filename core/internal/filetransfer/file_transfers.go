package filetransfer

import (
	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/pkg/observability"
)

type FileTransfer interface {
	Upload(task *Task) error
	Download(task *Task) error
}

// FileTransfers is a collection of file transfers by upload destination type.
type FileTransfers struct {
	// Default makes an HTTP request to the destination URL with the file contents.
	Default FileTransfer
}

// NewFileTransfers creates a new fileTransfers
func NewFileTransfers(
	client *retryablehttp.Client,
	logger *observability.CoreLogger,
	fileTransferStats FileTransferStats,
) *FileTransfers {
	defaultFileTransfer := &DefaultFileTransfer{
		logger:            logger,
		client:            client,
		fileTransferStats: fileTransferStats,
	}
	return &FileTransfers{
		Default: defaultFileTransfer,
	}
}

// Returns the appropriate fileTransfer depending on task
func (ft *FileTransfers) GetFileTransferForTask(task *Task) FileTransfer {
	return ft.Default
}
