package filetransfer

import (
	"context"
	"fmt"
	"io"
	"os"
	"path"
	"strings"

	"cloud.google.com/go/storage"
	"github.com/wandb/wandb/core/pkg/observability"
)

// GCSFileTransfer uploads or downloads files to/from GCS
type GCSFileTransfer struct {
	// client is the HTTP client for the file transfer
	client *storage.Client

	// logger is the logger for the file transfer
	logger *observability.CoreLogger

	// fileTransferStats is used to track upload/download progress
	fileTransferStats FileTransferStats

	// background context is used to create a reader and get the client
	ctx context.Context
}

// NewGCSFileTransfer creates a new fileTransfer
func NewGCSFileTransfer(
	logger *observability.CoreLogger,
	fileTransferStats FileTransferStats,
) *GCSFileTransfer {
	ctx := context.Background()
	client, err := storage.NewClient(ctx)
	if err != nil {
		// TODO: Handle error.
		return nil
	}

	fileTransfer := &GCSFileTransfer{
		logger:            logger,
		client:            client,
		fileTransferStats: fileTransferStats,
		ctx:               ctx,
	}
	return fileTransfer
}

// Upload uploads a file to the server
func (ft *GCSFileTransfer) Upload(task *Task) error {
	ft.logger.Debug("gcs file transfer: uploading file", "path", task.Path, "url", task.Url)

	return nil
}

// Download downloads a file from the server
func (ft *GCSFileTransfer) Download(task *Task) error {
	ft.logger.Debug("gcs reference file transfer: downloading file", "path", task.Path, "url", task.Url, "ref", task.Reference)
	reference := *task.Reference
	println("reference: ", reference)
	uriParts := strings.SplitN(reference[len("gs://"):], "/", 2)
	if len(uriParts) != 2 {
		return fmt.Errorf("invalid gsutil URI: %s", reference)
	}
	bucketName := uriParts[0]
	objectName := uriParts[1]

	// Get the bucket and the object
	bucket := ft.client.Bucket(bucketName)
	object := bucket.Object(objectName)

	// object can also be a folder
	r, err := object.NewReader(ft.ctx)
	if err != nil {
		// TODO: handle error
		return nil
	}
	defer r.Close()

	dir := path.Dir(task.Path)

	println("directory: ", dir)

	// Check if the directory already exists
	if _, err := os.Stat(dir); os.IsNotExist(err) {
		// Directory doesn't exist, create it
		if err := os.MkdirAll(dir, os.ModePerm); err != nil {
			// Handle the error if it occurs
			return err
		}
	} else if err != nil {
		// Handle other errors that may occur while checking directory existence
		return err
	}

	// // TODO: redo it to use the progress writer, to track the download progress
	// resp, err := ft.client.Get(task.Url)
	// if err != nil {
	// 	return err
	// }

	// open the file for writing and defer closing it
	file, err := os.Create(task.Path)
	if err != nil {
		return err
	}
	defer func(file *os.File) {
		if err := file.Close(); err != nil {
			ft.logger.CaptureError("file transfer: download: error closing file", err, "path", task.Path)
		}
	}(file)

	// defer func(file io.ReadCloser) {
	// 	if err := file.Close(); err != nil {
	// 		ft.logger.CaptureError("file transfer: download: error closing response reader", err, "path", task.Path)
	// 	}
	// }(resp.Body)

	_, err = io.Copy(file, r)
	if err != nil {
		return err
	}
	return nil
}
