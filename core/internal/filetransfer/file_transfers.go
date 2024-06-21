package filetransfer

import (
	"net/url"

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
	gcsReferenceFileTransfer := NewGCSFileTransfer(nil, logger, fileTransferStats)

	return &FileTransfers{
		Default:      defaultFileTransfer,
		GCSReference: gcsReferenceFileTransfer,
	}
}

// Returns the appropriate fileTransfer depending on task
func (ft *FileTransfers) GetFileTransferForTask(task *Task) FileTransfer {
	if task.Reference != nil {
		reference := *task.Reference

		uriParts, err := url.Parse(reference)
		if err != nil {
			return ft.Default
		} else if uriParts.Scheme == "gs" {
			return ft.GCSReference
		}
	}
	return ft.Default
}
