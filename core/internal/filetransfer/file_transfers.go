package filetransfer

import (
	"io"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/observability"
)

// FileTransfer handles run files and normal aritfacts.
type FileTransfer interface {
	// Upload uploads a file to the server.
	Upload(task *DefaultUploadTask) error

	// Download downloads a file from the server
	Download(task *DefaultDownloadTask) error
	DownloadTo(url string, dst io.Writer) error
}

// ArtifactFileTransfer handles reference artifacts.
type ArtifactFileTransfer interface {
	// Upload uploads a file to the server.
	Upload(task *DefaultUploadTask) error

	// Download downloads a file from the server
	Download(task *ReferenceArtifactDownloadTask) error
}

// FileTransfers is a collection of file transfers by upload destination type.
type FileTransfers struct {
	// Default makes an HTTP request to the destination URL with the file contents.
	Default FileTransfer

	// GCS connects to GCloud to upload/download files given their paths
	GCS ArtifactFileTransfer

	// S3 connects to AWS to upload/download files given their paths
	S3 ArtifactFileTransfer

	// Azure connects to Azure to upload/download files given their paths
	Azure ArtifactFileTransfer
}

// NewFileTransfers creates a new fileTransfers
func NewFileTransfers(
	client *retryablehttp.Client,
	logger *observability.CoreLogger,
	fileTransferStats FileTransferStats,
	extraHeaders map[string]string,
) *FileTransfers {
	defaultFileTransfer := NewDefaultFileTransfer(client, logger, fileTransferStats, extraHeaders)
	// NOTE: Cloud specific handlers are reference artifacts so we do NOT pass the extra headers to them (for now)
	gcsFileTransfer := NewGCSFileTransfer(nil, logger, fileTransferStats)
	s3FileTransfer := NewS3FileTransfer(nil, logger, fileTransferStats)
	azureFileTransfer := NewAzureFileTransfer(nil, logger, fileTransferStats)

	return &FileTransfers{
		Default: defaultFileTransfer,
		GCS:     gcsFileTransfer,
		S3:      s3FileTransfer,
		Azure:   azureFileTransfer,
	}
}
