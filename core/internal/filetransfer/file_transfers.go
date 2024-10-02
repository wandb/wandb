package filetransfer

import (
	"sync"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/observability"
)

type FileTransfer interface {
	Upload(task *DefaultUploadTask) error
	Download(task *DefaultDownloadTask) error
}

type ReferenceArtifactFileTransfer interface {
	Upload(task *ReferenceArtifactUploadTask) error
	Download(task *ReferenceArtifactDownloadTask) error
}

// FileTransfers is a collection of file transfers by upload destination type.
type FileTransfers struct {
	// Default makes an HTTP request to the destination URL with the file contents.
	Default FileTransfer

	// GCS connects to GCloud to upload/download files given their paths
	GCS     ReferenceArtifactFileTransfer
	GCSOnce *sync.Once

	// Logger is the logger that is passed to every new file transfer
	Logger *observability.CoreLogger

	// fileTransferStats keeps track of upload/download statistics
	FileTransferStats FileTransferStats
}

// NewFileTransfers creates a new fileTransfers
func NewFileTransfers(
	client *retryablehttp.Client,
	logger *observability.CoreLogger,
	fileTransferStats FileTransferStats,
) *FileTransfers {
	filetransfers := &FileTransfers{
		Logger:            logger,
		FileTransferStats: fileTransferStats,
		GCSOnce:           &sync.Once{},
	}

	defaultFileTransfer := NewDefaultFileTransfer(client, logger, fileTransferStats)
	filetransfers.Default = defaultFileTransfer

	return filetransfers
}

func (fts *FileTransfers) GetGCSFileTransfer() ReferenceArtifactFileTransfer {
	fts.GCSOnce.Do(func() {
		gcsFileTransfer, err := NewGCSFileTransfer(nil, fts.Logger, fts.FileTransferStats)
		if err == nil {
			fts.GCS = gcsFileTransfer
		} else {
			fts.Logger.Error("Unable to set up GCS file transfer", "error", err)
		}
	})
	return fts.GCS
}
