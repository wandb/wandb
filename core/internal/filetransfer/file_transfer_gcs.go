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

var ErrObjectIsDirectory = errors.New("object is a directory and cannot be downloaded")

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
	bucketName, objectName, err := parseReference(reference)
	if err != nil {
		ft.logger.CaptureError(fmt.Errorf("gcs file transfer: download: error parsing reference %s: %v", reference, err))
		return err
	}
	bucket := ft.client.Bucket(bucketName)

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

		// Try to download all objects under the reference
		g := new(errgroup.Group)
		g.SetLimit(maxWorkers)
		for _, name := range objectNames {
			objName := name // for closure in the goroutine
			g.Go(func() error {
				object, _, err := ft.GetObjectAndAttrs(bucket, task, objName)
				if err != nil {
					if errors.Is(err, ErrObjectIsDirectory) {
						ft.logger.Debug("gcs file transfer: download: skipping reference because it seems to be a folder", "reference", reference, "object", objName)
						return nil
					}
					ft.logger.CaptureError(fmt.Errorf("gcs file transfer: download: error when retrieving object for reference %s, key %s: %v", reference, objName, err))
					return err
				}
				localPath := getDownloadFilePath(objName, objectName, task.Path)
				return ft.DownloadFile(object, localPath)
			})
		}

		// Wait for all of the go routines to complete and return an error if any errored out
		if err := g.Wait(); err != nil {
			return err
		}
	case task.VersionId != nil:
		object, _, err := ft.GetObjectAndAttrs(bucket, task, objectName)
		if err != nil {
			if errors.Is(err, ErrObjectIsDirectory) {
				ft.logger.Debug("gcs file transfer: download: skipping reference because it seems to be a folder", "reference", reference)
				return nil
			}
			ft.logger.CaptureError(fmt.Errorf("gcs file transfer: download: error when retrieving object for reference %s: %v", reference, err))
			return err
		}
		return ft.DownloadFile(object, task.Path)
	default:
		object, objAttrs, err := ft.GetObjectAndAttrs(bucket, task, objectName)
		if err != nil {
			if errors.Is(err, ErrObjectIsDirectory) {
				ft.logger.Debug("gcs file transfer: download: skipping reference because it seems to be a folder", "reference", reference)
				return nil
			}
			ft.logger.CaptureError(fmt.Errorf("gcs file transfer: download: error when retrieving object/attributes for reference %s: %v", reference, err))
			return err
		}
		if objAttrs.Etag != task.Digest {
			err := fmt.Errorf("gcs file transfer: download: digest/etag mismatch for reference %s: etag %s does not match expected digest %s", reference, objAttrs.Etag, task.Digest)
			ft.logger.CaptureError(err)
			return err
		}
		return ft.DownloadFile(object, task.Path)
	}
	return nil
}

// DownloadFile downloads the contents of object into a file at path localPath
func (ft *GCSFileTransfer) DownloadFile(object *storage.ObjectHandle, localPath string) error {
	r, err := object.NewReader(ft.ctx)
	if err != nil {
		ft.logger.CaptureError(fmt.Errorf("gcs file transfer: download: unable to create reader for object %s, received error: %v", object.ObjectName(), err))
		return err
	}
	defer r.Close()

	// Check if the directory exists, and create it if it doesn't
	dir := path.Dir(localPath)
	if _, err := os.Stat(dir); os.IsNotExist(err) {
		if err := os.MkdirAll(dir, os.ModePerm); err != nil {
			ft.logger.CaptureError(fmt.Errorf("gcs file transfer: download: error creating directory to download into for object %s, error: %v", object.ObjectName(), err))
			return err
		}
	} else if err != nil {
		ft.logger.CaptureError(fmt.Errorf("gcs file transfer: download: error finding directory to download into for object %s, error: %v", object.ObjectName(), err))
		return err
	}

	// open the file for writing and defer closing it
	file, err := os.Create(localPath)
	if err != nil {
		ft.logger.CaptureError(fmt.Errorf("gcs file transfer: download: error creating file to download into for object %s, error: %v", object.ObjectName(), err))
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

/*
 * GetObjectAndAttrs returns the object handle and attributes if the object exists and corresponds with a file.
 * If the object corresponds to a directory, we return the ErrObjectIsDirectory error to skip downloading without failing.
 */
func (ft *GCSFileTransfer) GetObjectAndAttrs(bucket *storage.BucketHandle, task *Task, key string) (*storage.ObjectHandle, *storage.ObjectAttrs, error) {
	object, err := ft.GetObject(bucket, task, key)
	if err != nil {
		return nil, nil, err
	}
	if strings.HasSuffix(object.ObjectName(), "/") {
		return nil, nil, ErrObjectIsDirectory
	}

	attrs, err := object.Attrs(ft.ctx)
	// if object doesn't have an extension and has size 0, it might be a directory as we cut off the ending "/" in the manifest entry
	if err != nil && (path.Ext(object.ObjectName()) == "" && task.Size == 0) {
		key := key + "/"
		object, err := ft.GetObject(bucket, task, key)
		if err != nil {
			return nil, nil, err
		}

		// if the new key corresponds with an existing directory, it should return the attrs without an error
		_, err = object.Attrs(ft.ctx)
		if err != nil {
			return nil, nil, err
		}
		return nil, nil, ErrObjectIsDirectory
	} else if err != nil {
		return nil, nil, err
	}
	return object, attrs, nil
}

// GetObject returns the object handle given a bucket, key, and possible versionId
func (ft *GCSFileTransfer) GetObject(bucket *storage.BucketHandle, task *Task, key string) (*storage.ObjectHandle, error) {
	object := bucket.Object(key)
	if task.VersionId != nil {
		versionId, err := safeConvertToInt64(task.VersionId)
		if err != nil {
			err := fmt.Errorf("failed to convert VersionId: %v", err)
			ft.logger.CaptureError(err)
			return nil, err
		}
		object = object.Generation(versionId)
	}
	return object, nil
}

// parseReference parses the reference path and returns the bucket name and object name
func parseReference(reference string) (string, string, error) {
	uriParts, err := url.Parse(reference)
	if err != nil {
		return "", "", err
	}
	if uriParts.Scheme != "gs" {
		err := fmt.Errorf("invalid gsutil URI %s", reference)
		return "", "", err
	}
	bucketName := uriParts.Host
	objectName := strings.TrimPrefix(uriParts.Path, "/")
	return bucketName, objectName, nil
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
