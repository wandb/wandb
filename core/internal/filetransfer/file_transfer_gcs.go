package filetransfer

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path"
	"path/filepath"
	"strings"
	"sync"

	"cloud.google.com/go/storage"
	"github.com/googleapis/gax-go/v2"
	"github.com/wandb/wandb/core/internal/observability"
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

	// GCSOnce ensures that we only set up the GCS Client once
	GCSOnce *sync.Once
}

const maxGSWorkers int = 1000
const gcsScheme string = "gs"

var ErrObjectIsDirectory = errors.New("object is a directory and cannot be downloaded")

// NewGCSFileTransfer creates a new fileTransfer
func NewGCSFileTransfer(
	client GCSClient,
	logger *observability.CoreLogger,
	fileTransferStats FileTransferStats,
) *GCSFileTransfer {
	ctx := context.Background()
	fileTransfer := &GCSFileTransfer{
		logger:            logger,
		client:            client,
		fileTransferStats: fileTransferStats,
		ctx:               ctx,
		GCSOnce:           &sync.Once{},
	}
	return fileTransfer
}

// SetupClient sets up the GCS client if it is not currently set
func (ft *GCSFileTransfer) SetupClient() {
	ft.GCSOnce.Do(func() {
		if ft.client != nil {
			return
		}
		client, err := storage.NewClient(ft.ctx)
		if err != nil {
			ft.logger.Error("Unable to set up GCS client", "err", err)
			return
		}
		client.SetRetry(storage.WithBackoff(gax.Backoff{}), storage.WithMaxAttempts(5))
		ft.client = client
	})
}

// Upload uploads a file to the server.
func (ft *GCSFileTransfer) Upload(task *DefaultUploadTask) error {
	ft.logger.Debug("GCSFileTransfer: Upload: uploading file", "path", task.Path)

	return fmt.Errorf("not implemented yet")
}

// Download downloads a file from the server.
func (ft *GCSFileTransfer) Download(task *ReferenceArtifactDownloadTask) error {
	ft.logger.Debug(
		"GCSFileTransfer: Download: downloading file",
		"path", task.PathOrPrefix,
		"ref", task.Reference,
	)

	ft.SetupClient()
	if ft.client == nil {
		return fmt.Errorf("GCSFileTransfer: Download: Unable to set up GCS Client")
	}

	// Parse the reference path to get the scheme, bucket, and object
	bucketName, rootObjectName, err := parseCloudReference(task.Reference, gcsScheme)
	if err != nil {
		return ft.formatDownloadError("error parsing reference", err)
	}
	bucket := ft.client.Bucket(bucketName)

	var objectNames []string

	if task.HasSingleFile() {
		objectNames = []string{rootObjectName}
	} else {
		objectNames, err = ft.listObjectNamesWithPrefix(bucket, rootObjectName)
		if err != nil {
			return ft.formatDownloadError(
				fmt.Sprintf(
					"error getting objects in bucket %s under prefix %s",
					bucketName, rootObjectName,
				),
				err,
			)
		}
	}

	return ft.downloadFiles(bucket, rootObjectName, task, objectNames)
}

// listObjectNamesWithPrefix returns a list of names of all the objects
// with a specified prefix in the given bucket.
func (ft *GCSFileTransfer) listObjectNamesWithPrefix(
	bucket *storage.BucketHandle,
	prefix string,
) ([]string, error) {
	var objectNames []string
	it := bucket.Objects(ft.ctx, &storage.Query{Prefix: prefix})
	for {
		objAttrs, err := it.Next()
		if err == iterator.Done {
			break
		}
		if err != nil {
			return nil, err
		}
		objectNames = append(objectNames, objAttrs.Name)
	}
	return objectNames, nil
}

// downloadFiles concurrently gets and downloads all objects with the specified names
func (ft *GCSFileTransfer) downloadFiles(
	bucket *storage.BucketHandle,
	rootObjectName string,
	task *ReferenceArtifactDownloadTask,
	objectNames []string,
) error {
	var g errgroup.Group
	g.SetLimit(maxGSWorkers)
	for _, name := range objectNames {
		objectName := name // for closure in the goroutine
		g.Go(func() error {
			object, objAttrs, err := ft.getObjectAndAttrs(bucket, task, objectName)
			if err != nil {
				if errors.Is(err, ErrObjectIsDirectory) {
					ft.logger.Debug(
						"GCSFileTransfer: Download: skipping reference because it seems to be a folder",
						"bucket", bucket.BucketName(),
						"object", objectName,
					)
					return nil
				}
				return ft.formatDownloadError(
					fmt.Sprintf("error getting object %s", objectName),
					err,
				)
			}
			if task.ShouldCheckDigest() && objAttrs.Etag != task.Digest {
				err := fmt.Errorf(
					"digest/etag mismatch: etag %s does not match expected digest %s",
					objAttrs.Etag,
					task.Digest,
				)
				return ft.formatDownloadError("", err)
			}
			objectRelativePath, _ := strings.CutPrefix(objectName, rootObjectName)
			localPath := filepath.Join(task.PathOrPrefix, filepath.FromSlash(objectRelativePath))
			return ft.downloadFile(object, localPath)
		})
	}

	return g.Wait()
}

// downloadFile downloads the contents of object into a file at path localPath.
func (ft *GCSFileTransfer) downloadFile(
	object *storage.ObjectHandle,
	localPath string,
) (err error) {
	r, err := object.NewReader(ft.ctx)
	if err != nil {
		return ft.formatDownloadError("error creating reader", err)
	}
	defer func() {
		_ = r.Close()
	}()

	// Check if the directory exists, and create it if it doesn't
	dir := path.Dir(localPath)
	if err := os.MkdirAll(dir, os.ModePerm); err != nil {
		return ft.formatDownloadError(
			fmt.Sprintf("error creating download directory %s", dir),
			err,
		)
	}

	// open the file for writing and defer closing it
	file, err := os.Create(localPath)
	if err != nil {
		return ft.formatDownloadError(
			fmt.Sprintf("error creating download file %s", localPath),
			err,
		)
	}

	defer func() {
		fileError := file.Close()
		if err == nil {
			err = fileError
		}
	}()

	_, err = io.Copy(file, r)
	if err != nil {
		return ft.formatDownloadError(
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
	if strings.HasSuffix(key, "/") {
		return nil, nil, ErrObjectIsDirectory
	}
	object, err := ft.getObject(bucket, task, key)
	if err != nil {
		return nil, nil, err
	}

	attrs, err := object.Attrs(ft.ctx)
	// if object doesn't have an extension and has size 0, it might be a
	// directory as we cut off the ending "/" in the manifest entry.
	if errors.Is(err, storage.ErrObjectNotExist) &&
		(path.Ext(key) == "" && task.Size == 0) {
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
	versionId, ok := task.VersionIDNumber()
	object := bucket.Object(key)
	if ok {
		object = object.Generation(versionId)
	}
	return object, nil
}

func (ft *GCSFileTransfer) formatDownloadError(context string, err error) error {
	return fmt.Errorf("GCSFileTransfer: Download: %s: %v", context, err)
}
