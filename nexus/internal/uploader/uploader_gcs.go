package uploader

import (
	"cloud.google.com/go/storage"
	"context"
	"fmt"
	"github.com/wandb/wandb/nexus/pkg/observability"
	"io"
	"net/url"
	"os"
	"strings"
)

const ChunkSize = 1024 * 1024 * 4

// GCSUploader uploads files to Google Cloud Storage
type GCSUploader struct {
	// client is the HTTP client for the uploader
	client *storage.Client

	// logger is the logger for the uploader
	logger *observability.NexusLogger
}

// NewGCSUploader creates a new uploader
func NewGCSUploader(logger *observability.NexusLogger) *GCSUploader {
	// You do not need to provide any credentials when using a signed URL
	client, err := storage.NewClient(context.Background())
	if err != nil {
		logger.CaptureError("uploader: error creating GCS client", err)
	}

	uploader := &GCSUploader{
		client: client,
		logger: logger,
	}
	return uploader
}

func parseBucketAndObjectFromURL(signedURL string) (string, string, error) {
	parsedURL, err := url.Parse(signedURL)
	if err != nil {
		return "", "", err
	}

	pathParts := strings.Split(strings.TrimPrefix(parsedURL.Path, "/"), "/")

	if len(pathParts) < 2 {
		return "", "", fmt.Errorf("Invalid URL, can't extract bucket and object name")
	}

	bucket := pathParts[0]
	object := strings.Join(pathParts[1:], "/") + "?" + parsedURL.RawQuery

	return bucket, object, nil
}

// Upload uploads a file to the server
func (u *GCSUploader) Upload(task *UploadTask) error {
	u.logger.Debug("GCS uploader: uploading file", "path", task.Path, "url", task.Url)
	// open the file for reading and defer closing it
	file, err := os.Open(task.Path)
	if err != nil {
		task.outstandingDone()
		return err
	}
	defer func(file *os.File) {
		err := file.Close()
		if err != nil {
			u.logger.CaptureError("uploader: error closing file", err, "path", task.Path)
		}
	}(file)

	bucket, object, err := parseBucketAndObjectFromURL(task.Url)

	o := u.client.Bucket(bucket).Object(object)
	fmt.Println(o)

	// Optional: set a generation-match precondition to avoid potential race
	// conditions and data corruptions. The request to upload is aborted if the
	// object's generation number does not match your precondition.
	// For an object that does not yet exist, set the DoesNotExist precondition.
	//o = o.If(storage.Conditions{DoesNotExist: true})
	// If the live object already exists in your bucket, set instead a
	// generation-match precondition using the live object's generation number.
	// attrs, err := o.Attrs(ctx)
	// if err != nil {
	//      return fmt.Errorf("object.Attrs: %w", err)
	// }
	// o = o.If(storage.Conditions{GenerationMatch: attrs.Generation})

	// Upload an object with storage.Writer.
	wc := o.NewWriter(context.Background())
	if _, err = io.Copy(wc, file); err != nil {
		return fmt.Errorf("io.Copy: %w", err)
	}
	fmt.Println(err)
	if err := wc.Close(); err != nil {
		return fmt.Errorf("Writer.Close: %w", err)
	}

	//writer := storage.NewWriter(ctx, client, url)
	//writer.ChunkSize = ChunkSize
	//
	//if _, err = io.Copy(writer, file); err != nil {
	//	return fmt.Errorf("failed to copy data to the writer: %v", err)
	//}
	//
	//if err := writer.Close(); err != nil {
	//	return fmt.Errorf("failed to close writer: %v", err)
	//}

	task.outstandingDone()
	return nil
}
