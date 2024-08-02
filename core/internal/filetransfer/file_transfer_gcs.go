package filetransfer

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/url"
	"os"
	"path"
	"strings"

	"cloud.google.com/go/storage"
	"github.com/googleapis/gax-go/v2"
	"github.com/wandb/wandb/core/pkg/observability"
	"golang.org/x/sync/errgroup"
	"google.golang.org/api/iterator"
)

type GCSClient interface {
	Bucket(name string) *storage.BucketHandle
	SetRetry(opts ...storage.RetryOption)
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

const maxWorkers int = 1000

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
			logger.CaptureError(fmt.Errorf("gcs file transfer: error creating new gcs client: %v", err))
			return nil
		}
		client.SetRetry(storage.WithBackoff(gax.Backoff{}), storage.WithMaxAttempts(5))
	}

	fileTransfer := &GCSFileTransfer{
		logger:            logger,
		client:            client,
		fileTransferStats: fileTransferStats,
		ctx:               ctx,
	}
	return fileTransfer
}

// CanHandle returns true if GCSFileTransfer can upload/download the task
func (ft *GCSFileTransfer) CanHandle(task *Task) bool {
	if task.Reference != nil {
		reference := *task.Reference
		uriParts, err := url.Parse(reference)
		if err != nil {
			return false
		} else if uriParts.Scheme == "gs" {
			return true
		}
	}
	return false
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
		err := fmt.Errorf("gcs file transfer: download: reference is nil")
		ft.logger.CaptureError(err)
		return err
	}
	reference := *task.Reference

	// Parse the reference path to get the scheme, bucket, and object
	uriParts, err := url.Parse(reference)
	if err != nil {
		ft.logger.CaptureError(fmt.Errorf("gcs file transfer: download: error parsing reference %s: %v", reference, err))
		return err
	}
	if uriParts.Scheme != "gs" {
		err := fmt.Errorf("gcs file transfer: download: invalid gsutil URI %s", reference)
		ft.logger.CaptureError(err)
		return err
	}
	bucketName := uriParts.Host
	bucket := ft.client.Bucket(bucketName)
	objectName := strings.TrimPrefix(uriParts.Path, "/")

	switch {
	case task.Digest == reference:
		// If not using checksum, get all objects under the reference
		var objectNames []string
		query := &storage.Query{Prefix: objectName}
		it := bucket.Objects(ft.ctx, query)
		for {
			objAttrs, err := it.Next()
			if err == iterator.Done {
				break
			}
			if err != nil {
				ft.logger.CaptureError(fmt.Errorf("gcs file transfer: download: error iterating through gcs bucket %s with prefix %s for reference %s: %v", bucketName, objectName, reference, err))
				return err
			}
			objectNames = append(objectNames, objAttrs.Name)
		}

		g := new(errgroup.Group)
		g.SetLimit(maxWorkers)
		for _, name := range objectNames {
			objName := name // for closure in the goroutine
			g.Go(func() error {
				object := bucket.Object(objName)
				localPath := getDownloadFilePath(objName, objectName, task.Path)
				err := ft.DownloadFile(object, localPath)
				if err != nil {
					isDir, err := ft.IsDir(object, task.Size)
					if err != nil {
						ft.logger.CaptureError(fmt.Errorf("gcs file transfer: download: error checking if reference is a directory %s: %v", reference, err))
						return err
					} else if isDir {
						ft.logger.Debug("gcs file transfer: download: skipping reference because it seems to be a folder", "reference", reference)
						return nil
					}
					ft.logger.CaptureError(fmt.Errorf("gcs file transfer: download: error when downloading file for reference %s: %v", reference, err))
					return err
				}
				return nil
			})
		}

		// Wait for all of the go routines to complete and return an error if any errored out
		if err := g.Wait(); err != nil {
			return err
		}
	case task.VersionId != nil:
		versionId, err := safeConvertToInt64(task.VersionId)
		if err != nil {
			ft.logger.CaptureError(fmt.Errorf("failed to convert VersionId: %v", err))
		}
		object := bucket.Object(objectName).Generation(versionId)
		err = ft.DownloadFile(object, task.Path)
		if err != nil {
			isDir, err := ft.IsDir(object, task.Size)
			if err != nil {
				ft.logger.CaptureError(fmt.Errorf("gcs file transfer: download: error checking if reference is a directory %s: %v", reference, err))
				return err
			} else if isDir {
				ft.logger.Debug("gcs file transfer: download: skipping reference because it seems to be a folder", "reference", reference)
				return nil
			}
			ft.logger.CaptureError(fmt.Errorf("gcs file transfer: download: error while downloading file for reference %s: %v", reference, err))
			return err
		}
	default:
		object := bucket.Object(objectName)
		objAttrs, err := object.Attrs(ft.ctx)
		if err != nil {
			isDir, err := ft.IsDir(object, task.Size)
			if err != nil {
				ft.logger.CaptureError(fmt.Errorf("gcs file transfer: download: error checking if reference is a directory %s: %v", reference, err))
				return err
			} else if isDir {
				ft.logger.Debug("gcs file transfer: download: skipping reference because it seems to be a folder", "reference", reference)
				return nil
			}
			ft.logger.CaptureError(fmt.Errorf("gcs file transfer: download: unable to fetch object attributes for %s for reference %s: %v", objectName, reference, err))
			return err
		}
		if objAttrs.Etag != task.Digest {
			err := fmt.Errorf("gcs file transfer: download: digest/etag mismatch for reference %s: etag %s does not match expected digest %s", reference, objAttrs.Etag, task.Digest)
			ft.logger.CaptureError(err)
			return err
		}
		err = ft.DownloadFile(object, task.Path)
		if err != nil {
			ft.logger.CaptureError(fmt.Errorf("gcs file transfer: download: error while downloading file for reference %s: %v", reference, err))
			return err
		}
	}
	return nil
}

// DownloadFile downloads the contents of object into a file at path localPath
func (ft *GCSFileTransfer) DownloadFile(object *storage.ObjectHandle, localPath string) error {
	r, err := object.NewReader(ft.ctx)
	if err != nil {
		ft.logger.CaptureError(fmt.Errorf("unable to create reader for object %s, received error: %v", object.ObjectName(), err))
		return err
	}
	defer r.Close()

	// Check if the directory exists, and create it if it doesn't
	dir := path.Dir(localPath)
	if _, err := os.Stat(dir); os.IsNotExist(err) {
		if err := os.MkdirAll(dir, os.ModePerm); err != nil {
			return err
		}
	} else if err != nil {
		return err
	}

	// open the file for writing and defer closing it
	file, err := os.Create(localPath)
	if err != nil {
		return err
	}
	defer func(file *os.File) {
		if err := file.Close(); err != nil {
			ft.logger.CaptureError(fmt.Errorf("gcs file transfer: download: error closing file %s: %v", localPath, err))
		}
	}(file)

	_, err = io.Copy(file, r)
	if err != nil {
		ft.logger.CaptureError(fmt.Errorf("gcs file transfer: download: error copying object %s into file %s: %v", object.ObjectName(), localPath, err))
		return err
	}

	return nil
}

// isDir returns true if the object key and its size indicate that it might be a directory
func (ft *GCSFileTransfer) IsDir(object *storage.ObjectHandle, size int64) (bool, error) {
	if (strings.HasSuffix(object.ObjectName(), "/") && size == 0) {
		return true, nil
	} else if (path.Ext(object.ObjectName()) == "" && size == 0) {
		_, err := object.Attrs(ft.ctx)
		// this should only return this error in the case that its a folder. Otherwise, we wouldn't even be able to get the object
		if err != nil && errors.Is(err, storage.ErrObjectNotExist) {
			return true, nil
		} else if (err != nil) {
			return false, err
		}
	}
	return false, nil
}

// getDownloadFilePath returns the file path to download the file to, removing duplicate info from the extension
func getDownloadFilePath(objectName string, prefix string, baseFilePath string) string {
	ext, _ := strings.CutPrefix(objectName, prefix)
	localPath := baseFilePath + ext
	return localPath
}

// safeConvertToInt64 attempts to convert an interface{} to an int64 value
func safeConvertToInt64(value interface{}) (int64, error) {
	floatVal, ok := value.(float64)
	if !ok {
		return 0, fmt.Errorf("value is not a float64: %v", value)
	}
	return int64(floatVal), nil
}
