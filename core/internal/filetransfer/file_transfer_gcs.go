package filetransfer

import (
	"context"
	"errors"
	"io"
	"net/url"
	"os"
	"path"
	"strings"

	"cloud.google.com/go/storage"
	"github.com/wandb/wandb/core/pkg/observability"
	"google.golang.org/api/iterator"
)

type GCSClient interface {
	Bucket(name string) *storage.BucketHandle
}

// GCSFileTransfer uploads or downloads files to/from GCS
type GCSFileTransfer struct {
	// client is the HTTP client for the file transfer
	client GCSClient

	// logger is the logger for the file transfer
	logger *observability.CoreLogger

	// fileTransferStats is used to track upload/download progress
	fileTransferStats FileTransferStats

	// background context is used to create a reader and get the client
	ctx context.Context
}

// NewGCSFileTransfer creates a new fileTransfer
func NewGCSFileTransfer(
	client GCSClient,
	logger *observability.CoreLogger,
	fileTransferStats FileTransferStats,
) *GCSFileTransfer {
	ctx := context.Background()
	if client == nil {
		var err error
		client, err = storage.NewClient(ctx)
		if err != nil {
			logger.CaptureError("gcs file transfer: error creating new gcs client", err)
			return nil
		}
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
	ft.logger.Debug("gcs file transfer: downloading file", "path", task.Path, "url", task.Url, "ref", task.Reference)
	if task.Reference == nil {
		ft.logger.Error("gcs file transfer: download: reference is nil")
		return errors.New("gcs file transfer: download: reference is nil")
	}
	reference := *task.Reference

	uriParts, err := url.Parse(reference)
	if err != nil {
		ft.logger.CaptureError("gcs file transfer: download: error parsing reference", err, "reference", reference)
		return err
	}
	if uriParts.Scheme != "gs" {
		ft.logger.CaptureError("gcs file transfer: download: invalid gsutil URI", err, "reference", reference)
		return errors.New("gcs file transfer: download: invalid gsutil URI")
	}
	bucketName := uriParts.Host
	objectName := strings.TrimPrefix(uriParts.Path, "/")

	// Get the bucket and the object
	bucket := ft.client.Bucket(bucketName)
	var objects []*storage.ObjectHandle

	switch {
	case task.Digest == reference:
		// If not using checksum, get all objects under the reference
		query := &storage.Query{Prefix: objectName}
		it := bucket.Objects(ft.ctx, query)
		for {
			objAttrs, err := it.Next()
			if err == iterator.Done {
				break
			}
			if err != nil {
				ft.logger.CaptureError("gcs file transfer: download: error while iterating through objects in gcs bucket", err, "reference", reference)
				return err
			}
			object := bucket.Object(objAttrs.Name)
			objects = append(objects, object)
		}
	case task.VersionId != nil:
		object := bucket.Object(objectName).Generation(int64(task.VersionId.(float64)))
		objects = append(objects, object)
	default:
		object := bucket.Object(objectName)
		objAttrs, err := object.Attrs(ft.ctx)
		if err != nil {
			ft.logger.CaptureError("gcs file transfer: download: unable to fetch object attributes", err, "reference", reference)
			return err
		}
		if objAttrs.Etag != task.Digest {
			ft.logger.CaptureError("gcs file transfer: download: digest/etag mismatch", err, "reference", reference, "etag", objAttrs.Etag, "digest", task.Digest)
			return err
		}
		objects = append(objects, object)
	}

	c := make(chan error)
	for _, object := range objects {
		go func(obj *storage.ObjectHandle) {
			objName := obj.ObjectName()
			r, err := obj.NewReader(ft.ctx)
			if err != nil {
				ft.logger.CaptureError("gcs file transfer: download: unable to create reader", err, "reference", reference, "versionId", task.VersionId, "object", objName)
				c <- err
				return
			}
			defer r.Close()

			ext, _ := strings.CutPrefix(objName, objectName)
			localPath := task.Path + ext
			dir := path.Dir(localPath)

			// Check if the directory already exists
			if _, err := os.Stat(dir); os.IsNotExist(err) {
				// Directory doesn't exist, create it
				if err := os.MkdirAll(dir, os.ModePerm); err != nil {
					// Handle the error if it occurs
					c <- err
					return
				}
			} else if err != nil {
				// Handle other errors that may occur while checking directory existence
				c <- err
				return
			}

			// open the file for writing and defer closing it
			file, err := os.Create(localPath)
			if err != nil {
				c <- err
				return
			}
			defer func(file *os.File) {
				if err := file.Close(); err != nil {
					ft.logger.CaptureError("gcs file transfer: download: error closing file", err, "path", localPath)
				}
			}(file)

			_, err = io.Copy(file, r)
			if err != nil {
				ft.logger.CaptureError("gcs file transfer: download: error copying file", err, "reference", reference, "object", objName)
				c <- err
				return
			}
			c <- nil
		}(object)
	}
	for range objects {
		err := <-c
		if err != nil {
			ft.logger.CaptureError("gcs file transfer: download: error when downloading reference", err, "reference", reference)
		}
	}
	return nil
}
