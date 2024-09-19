package filetransfer

import (
	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/pkg/observability"
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
	GCS     ReferenceArtifactFileTransfer
	S3      ReferenceArtifactFileTransfer
}

// NewFileTransfers creates a new fileTransfers
func NewFileTransfers(
	client *retryablehttp.Client,
	logger *observability.CoreLogger,
	fileTransferStats FileTransferStats,
) *FileTransfers {
	filetransfers := &FileTransfers{}

	defaultFileTransfer := NewDefaultFileTransfer(client, logger, fileTransferStats)
	filetransfers.Default = defaultFileTransfer

	gcsFileTransfer := NewGCSFileTransfer(nil, logger, fileTransferStats)
	filetransfers.GCS = gcsFileTransfer

	s3FileTransfer, err := NewS3FileTransfer(nil, logger, fileTransferStats)
	if err == nil {
		filetransfers.S3 = s3FileTransfer
	} else {
		logger.CaptureError(err)
	}

	return filetransfers
}
