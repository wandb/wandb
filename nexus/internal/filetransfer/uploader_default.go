package filetransfer

import (
	"net/http"
	"os"
	"strings"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/nexus/pkg/observability"
)

// DefaultFileTransfer uploads or downloads files to/from the server
type DefaultFileTransfer struct {
	// client is the HTTP client for the file transfer
	client *retryablehttp.Client

	// logger is the logger for the file transfer
	logger *observability.NexusLogger
}

// NewDefaultFileTransfer creates a new fileTransfer
func NewDefaultFileTransfer(logger *observability.NexusLogger, client *retryablehttp.Client) *DefaultFileTransfer {
	fileTransfer := &DefaultFileTransfer{
		logger: logger,
		client: client,
	}
	return fileTransfer
}

// Upload uploads a file to the server
func (ft *DefaultFileTransfer) Upload(task *UploadTask) error {
	ft.logger.Debug("default file transfer: uploading file", "path", task.Path, "url", task.Url)
	// open the file for reading and defer closing it
	file, err := os.Open(task.Path)
	if err != nil {
		return err
	}
	defer func(file *os.File) {
		err := file.Close()
		if err != nil {
			ft.logger.CaptureError("file transfer: upload: error closing file", err, "path", task.Path)
		}
	}(file)

	req, err := retryablehttp.NewRequest(
		http.MethodPut,
		task.Url,
		file,
	)

	for _, header := range task.Headers {
		parts := strings.Split(header, ":")
		req.Header.Set(parts[0], parts[1])
	}

	if err != nil {
		return err
	}

	if _, err = ft.client.Do(req); err != nil {
		return err
	}

	return nil
}
