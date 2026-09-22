//go:build cloud_http

package filetransfer

import (
	"context"
	"fmt"
	"io"
	"path/filepath"
	"strings"
	"sync"

	"github.com/aws/aws-sdk-go-v2/config"
	"golang.org/x/sync/errgroup"

	"github.com/wandb/wandb/core/internal/fileutil"
	"github.com/wandb/wandb/core/internal/observability"
)

// S3Object identifies an object, optionally at a specific version.
type S3Object struct {
	Bucket    string
	Key       string
	VersionID string
}

// S3ObjectPage contains one page of object keys.
type S3ObjectPage struct {
	Keys      []string
	Truncated bool
	NextToken string
}

// S3ObjectVersion identifies an object's version and content digest.
type S3ObjectVersion struct {
	Key       string
	VersionID string
	ETag      string
}

// S3VersionPage contains one page of versions. Both markers identify the next page.
type S3VersionPage struct {
	Versions            []S3ObjectVersion
	Truncated           bool
	NextKeyMarker       string
	NextVersionIDMarker string
}

// S3Client provides the object reads needed by reference artifacts.
type S3Client interface {
	GetObject(context.Context, S3Object) (io.ReadCloser, error)
	GetObjectETag(context.Context, S3Object) (string, error)
	ListObjects(context.Context, string, string, string) (S3ObjectPage, error)
	ListVersions(context.Context, string, string, string, string) (S3VersionPage, error)
}

const maxS3Workers int = 500
const s3Scheme string = "s3"

// S3FileTransfer uploads or downloads files to/from s3
type S3FileTransfer struct {
	// client is the HTTP client for the file transfer
	client S3Client

	// logger is the logger for the file transfer
	logger *observability.CoreLogger

	// fileTransferStats is used to track upload/download progress
	fileTransferStats FileTransferStats

	// background context is used to create a reader and get the client
	ctx context.Context

	// S3Once ensures that we only set up the S3 Client once
	S3Once *sync.Once
}

// News3FileTransfer creates a new fileTransfer.
func NewS3FileTransfer(
	client S3Client,
	logger *observability.CoreLogger,
	fileTransferStats FileTransferStats,
) *S3FileTransfer {
	ctx := context.Background()
	return &S3FileTransfer{
		logger:            logger,
		client:            client,
		fileTransferStats: fileTransferStats,
		ctx:               ctx,
		S3Once:            &sync.Once{},
	}
}

// SetupClient sets up the S3 client if it is not currently set
func (ft *S3FileTransfer) SetupClient() {
	ft.S3Once.Do(func() {
		if ft.client != nil {
			return
		}
		cfg, err := config.LoadDefaultConfig(ft.ctx)
		if err != nil {
			ft.logger.Error("Unable to load config to set up S3 client", "err", err)
			return
		}
		client, err := newS3HTTPClient(ft.ctx, &cfg)
		if err != nil {
			ft.logger.Error("Unable to set up S3 HTTP client", "err", err)
			return
		}
		ft.client = client
	})
}

// Upload implements ArtifactFileTransfer.Upload
func (ft *S3FileTransfer) Upload(task *DefaultUploadTask) error {
	ft.logger.Debug("S3 file transfer: uploading file", "path", task.Path)

	return nil
}

// Download implements ArtifactFileTransfer.Download
func (ft *S3FileTransfer) Download(task *ReferenceArtifactDownloadTask) error {
	ft.logger.Debug(
		"s3 file transfer: downloading file",
		"path", task.PathOrPrefix,
		"ref", task.Reference,
	)

	ft.SetupClient()
	if ft.client == nil {
		return fmt.Errorf("S3FileTransfer: Download: Unable to set up S3 Client")
	}

	// Parse the reference path to get the scheme, bucket, and object
	bucketName, rootObjectName, err := parseCloudReference(task.Reference, s3Scheme)
	if err != nil {
		return ft.formatDownloadError("error parsing reference", err)
	}

	var getObjectInputs []S3Object
	if task.HasSingleFile() {
		getObjInput, err := ft.findObjectFromTask(bucketName, rootObjectName, task)
		if err != nil {
			return ft.formatDownloadError("error constructing object input", err)
		}
		getObjectInputs = []S3Object{getObjInput}
	} else {
		getObjectInputs, err = ft.listObjectsWithPrefix(bucketName, rootObjectName)
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
	err = ft.downloadFiles(rootObjectName, getObjectInputs, task.PathOrPrefix)
	if err != nil {
		return ft.formatDownloadError("error downloading object", err)
	}
	return nil
}

// findObjectFromTask finds the s3 object that matches the versionId and
// digest/ETag specified by the task, and returns a struct that we can use
// to access that s3 object.
func (ft *S3FileTransfer) findObjectFromTask(
	bucketName string,
	objectName string,
	task *ReferenceArtifactDownloadTask,
) (S3Object, error) {
	object := S3Object{Bucket: bucketName, Key: objectName}
	if versionID, ok := task.VersionIDString(); ok {
		object.VersionID = versionID
	}
	etag, err := ft.client.GetObjectETag(ft.ctx, object)
	if err != nil {
		return S3Object{}, err
	}
	if strings.Trim(etag, "\"") == task.Digest {
		return object, nil
	}
	if task.VersionId != nil {
		return S3Object{}, fmt.Errorf(
			"digest/etag mismatch: etag %s does not match expected digest %s",
			etag,
			task.Digest,
		)
	}
	return ft.getCorrectObjectVersion(object, task.Digest)
}

// listObjectsWithPrefix returns every object matching the prefix.
func (ft *S3FileTransfer) listObjectsWithPrefix(bucket, prefix string) ([]S3Object, error) {
	var objects []S3Object
	var token string
	for {
		page, err := ft.client.ListObjects(ft.ctx, bucket, prefix, token)
		if err != nil {
			return nil, err
		}
		for _, key := range page.Keys {
			objects = append(objects, S3Object{Bucket: bucket, Key: key})
		}
		if !page.Truncated {
			return objects, nil
		}
		if page.NextToken == "" || page.NextToken == token {
			return nil, fmt.Errorf(
				"S3 listing returned a truncated page without a new continuation token",
			)
		}
		token = page.NextToken
	}
}

// getCorrectObjectVersion finds an exact key and ETag, following both version markers.
func (ft *S3FileTransfer) getCorrectObjectVersion(
	object S3Object,
	digest string,
) (S3Object, error) {
	var keyMarker, versionMarker string
	for {
		page, err := ft.client.ListVersions(
			ft.ctx,
			object.Bucket,
			object.Key,
			keyMarker,
			versionMarker,
		)
		if err != nil {
			return S3Object{}, err
		}
		for _, version := range page.Versions {
			if version.Key == object.Key && strings.Trim(version.ETag, "\"") == digest {
				object.VersionID = version.VersionID
				return object, nil
			}
		}
		if !page.Truncated {
			break
		}
		if page.NextKeyMarker == "" ||
			(page.NextKeyMarker == keyMarker && page.NextVersionIDMarker == versionMarker) {
			return S3Object{}, fmt.Errorf(
				"S3 version listing returned a truncated page without new markers",
			)
		}
		keyMarker, versionMarker = page.NextKeyMarker, page.NextVersionIDMarker
	}
	return S3Object{}, fmt.Errorf(
		"digest/etag mismatch: unable to find version with expected digest %s",
		digest,
	)
}

// downloadFiles downloads all of the objects in the specified bucket.
func (ft *S3FileTransfer) downloadFiles(
	rootObjectName string,
	getObjectInputs []S3Object,
	basePath string,
) error {
	g := new(errgroup.Group)
	g.SetLimit(maxS3Workers)
	for _, input := range getObjectInputs {
		g.Go(func() error {
			objectRelativePath, matches := strings.CutPrefix(input.Key, rootObjectName)
			if !matches {
				return fmt.Errorf("S3 listing returned an object outside the requested prefix")
			}
			objectRelativePath = strings.TrimLeft(objectRelativePath, "/")
			relativePath := filepath.FromSlash(objectRelativePath)
			if relativePath != "" && !filepath.IsLocal(relativePath) {
				return fmt.Errorf("S3 object path escapes the download directory")
			}
			localPath := filepath.Join(basePath, relativePath)
			return ft.downloadFile(input, localPath)
		})
	}

	return g.Wait()
}

// downloadFile downloads the content of an object to the specified path.
func (ft *S3FileTransfer) downloadFile(
	getObjInput S3Object,
	localPath string,
) error {
	object, err := ft.client.GetObject(ft.ctx, getObjInput)
	if err != nil {
		return err
	}
	defer func() {
		_ = object.Close()
	}()

	return fileutil.CopyReaderToFile(object, localPath)
}

func (ft *S3FileTransfer) formatDownloadError(ctx string, err error) error {
	return fmt.Errorf("S3FileTransfer: Download: %s: %v", ctx, err)
}
