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
) (*GCSFileTransfer, error) {
	ctx := context.Background()
	if client == nil {
		var err error
		client, err = storage.NewClient(ctx)
		if err != nil {
			return nil, err
		}
		client.SetRetry(storage.WithBackoff(gax.Backoff{}), storage.WithMaxAttempts(5))
	}
	fileTransfer := &GCSFileTransfer{
		logger:            logger,
		client:            client,
		fileTransferStats: fileTransferStats,
		ctx:               ctx,
	}
	return fileTransfer, nil
}

// Upload uploads a file to the server.
func (ft *GCSFileTransfer) Upload(task *ReferenceArtifactUploadTask) error {
	ft.logger.Debug("GCSFileTransfer: Upload: uploading file", "path", task.Path)

	return fmt.Errorf("not implemented yet")
}

// Download downloads a file from the server.
func (ft *GCSFileTransfer) Download(task *ReferenceArtifactDownloadTask) error {
	ft.logger.Debug(
		"GCSFileTransfer: Download: downloading file",
		"path", task.Path,
		"ref", task.Reference,
	)

	reference := task.Reference

	// Parse the reference path to get the scheme, bucket, and object
	bucketName, objectPathPrefix, err := parseReference(reference)
	if err != nil {
		return formatDownloadError("error parsing reference", err)
	}
	bucket := ft.client.Bucket(bucketName)

	// If not using checksum, we set the digest to the reference
	if task.Digest == reference {
		// Get all of the objects under the reference
		var objectNames []string
		query := &storage.Query{Prefix: objectPathPrefix}
		it := bucket.Objects(ft.ctx, query)
		for {
			objAttrs, err := it.Next()
			if err == iterator.Done {
				break
			}
			if err != nil {
				return formatDownloadError("error iterating through objects", err)
			}
			objectNames = append(objectNames, objAttrs.Name)
		}

		// Try to download all objects under the reference
		g := new(errgroup.Group)
		g.SetLimit(maxWorkers)
		for _, name := range objectNames {
			objectName := name // for closure in the goroutine
			g.Go(func() error {
				object, _, err := ft.getObjectAndAttrs(bucket, task, objectName)
				if err != nil {
					if errors.Is(err, ErrObjectIsDirectory) {
						ft.logger.Debug(
							"GCSFileTransfer: Download: skipping reference because it seems to be a folder",
							"reference", reference,
							"object", objectName,
						)
						return nil
					}
					return formatDownloadError(
						fmt.Sprintf("error getting object %s", objectName),
						err,
					)
				}
				localPath := getDownloadFilePath(objectName, objectPathPrefix, task.Path)
				return ft.downloadFile(object, localPath)
			})
		}

		// Wait for all of the go routines to complete and return an error
		// if any errored out
		if err := g.Wait(); err != nil {
			return formatDownloadError("", err)
		}
	} else {
		objectName := objectPathPrefix
		object, objAttrs, err := ft.getObjectAndAttrs(bucket, task, objectName)
		if err != nil {
			if errors.Is(err, ErrObjectIsDirectory) {
				ft.logger.Debug(
					"GCSFileTransfer: Download: skipping reference because it seems to be a folder",
					"reference", reference,
				)
				return nil
			}
			return formatDownloadError(fmt.Sprintf("error getting object %s", objectName), err)
		}
		if objAttrs.Etag != task.Digest {
			err := fmt.Errorf(
				"digest/etag mismatch: etag %s does not match expected digest %s",
				objAttrs.Etag,
				task.Digest,
			)
			return formatDownloadError("", err)
		}
		return ft.downloadFile(object, task.Path)
	}
	return nil
}

// DownloadFile downloads the contents of object into a file at path localPath.
func (ft *GCSFileTransfer) downloadFile(
	object *storage.ObjectHandle,
	localPath string,
) (err error) {
	r, err := object.NewReader(ft.ctx)
	if err != nil {
		return formatDownloadError("error creating reader", err)
	}
	defer r.Close()

	// Check if the directory exists, and create it if it doesn't
	dir := path.Dir(localPath)
	if err := os.MkdirAll(dir, os.ModePerm); err != nil {
		return formatDownloadError(
			fmt.Sprintf("error creating download directory %s", dir),
			err,
		)
	}

	// open the file for writing and defer closing it
	file, err := os.Create(localPath)
	if err != nil {
		return formatDownloadError(
			fmt.Sprintf("error creating download file %s", localPath),
			err,
		)
	}

	defer func(file *os.File) {
		fileError := file.Close()
		if err == nil {
			err = formatDownloadError(
				fmt.Sprintf("error closing file %s", localPath),
				fileError,
			)
		}
	}(file)

	_, err = io.Copy(file, r)
	if err != nil {
		return formatDownloadError(
			fmt.Sprintf("error copying file %s", localPath),
			err,
		)
	}

	return nil
}

// getObjectAndAttrs returns the object handle and attributes if the object
// exists and corresponds with a file.
//
// If the object corresponds to a directory, we return the ErrObjectIsDirectory
// error to skip downloading without failing.
func (ft *GCSFileTransfer) getObjectAndAttrs(
	bucket *storage.BucketHandle,
	task *ReferenceArtifactDownloadTask,
	key string,
) (*storage.ObjectHandle, *storage.ObjectAttrs, error) {
	object, err := ft.getObject(bucket, task, key)
	if err != nil {
		return nil, nil, err
	}
	if strings.HasSuffix(object.ObjectName(), "/") {
		return nil, nil, ErrObjectIsDirectory
	}

	attrs, err := object.Attrs(ft.ctx)
	// if object doesn't have an extension and has size 0, it might be a
	// directory as we cut off the ending "/" in the manifest entry.
	if err != nil && (path.Ext(object.ObjectName()) == "" && task.Size == 0) {
		key := key + "/"
		object, err := ft.getObject(bucket, task, key)
		if err != nil {
			return nil, nil, err
		}

		// if the new key corresponds with an existing directory, it should
		// return the attrs without an error
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

// getObject returns the object handle given a bucket, key, and task object
// with a possible versionId.
func (ft *GCSFileTransfer) getObject(
	bucket *storage.BucketHandle,
	task *ReferenceArtifactDownloadTask,
	key string,
) (*storage.ObjectHandle, error) {
	object := bucket.Object(key)
	if task.VersionId != nil {
		versionId, err := safeConvertToInt64(task.VersionId)
		if err != nil {
			err := fmt.Errorf("failed to convert VersionId: %v", err)
			return nil, err
		}
		object = object.Generation(versionId)
	}
	return object, nil
}

// parseReference parses the reference path and returns the bucket name and
// object name.
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

// getDownloadFilePath returns the file path to download the file to when
// removing duplicate info from the extension.
func getDownloadFilePath(objectName string, prefix string, baseFilePath string) string {
	ext, _ := strings.CutPrefix(objectName, prefix)
	localPath := baseFilePath + ext
	return localPath
}

// safeConvertToInt64 attempts to convert an interface{} to an int64 value.
func safeConvertToInt64(value interface{}) (int64, error) {
	floatVal, ok := value.(float64)
	if !ok {
		return 0, fmt.Errorf("value is not a float64: %v", value)
	}
	return int64(floatVal), nil
}

func formatDownloadError(context string, err error) error {
	return fmt.Errorf("GCSFileTransfer: Download: %s: %v", context, err)
}
