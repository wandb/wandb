package filetransfer

import (
	"context"
	"fmt"
	"path/filepath"
	"strings"
	"sync"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
	"github.com/wandb/wandb/core/internal/fileutil"
	"github.com/wandb/wandb/core/internal/observability"
	"golang.org/x/sync/errgroup"
)

type S3Client interface {
	GetObject(ctx context.Context, params *s3.GetObjectInput, optFns ...func(*s3.Options)) (*s3.GetObjectOutput, error)
	GetObjectAttributes(ctx context.Context, params *s3.GetObjectAttributesInput, optFns ...func(*s3.Options)) (*s3.GetObjectAttributesOutput, error)
	ListObjectsV2(ctx context.Context, params *s3.ListObjectsV2Input, optFns ...func(*s3.Options)) (*s3.ListObjectsV2Output, error)
	ListObjectVersions(ctx context.Context, params *s3.ListObjectVersionsInput, optFns ...func(*s3.Options)) (*s3.ListObjectVersionsOutput, error)
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
		client := s3.NewFromConfig(cfg)
		ft.client = client
	})
}

// Upload uploads a file to the server.
func (ft *S3FileTransfer) Upload(task *ReferenceArtifactUploadTask) error {
	ft.logger.Debug("S3 file transfer: uploading file", "path", task.PathOrPrefix)

	return nil
}

// Download downloads a file from the server.
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

	var getObjectInputs []*s3.GetObjectInput
	if task.HasSingleFile() {
		getObjInput, err := ft.findObjectFromTask(bucketName, rootObjectName, task)
		if err != nil {
			return ft.formatDownloadError("error constructing object input", err)
		}
		getObjectInputs = []*s3.GetObjectInput{getObjInput}
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
) (*s3.GetObjectInput, error) {
	var getObjInput *s3.GetObjectInput = &s3.GetObjectInput{
		Bucket: aws.String(bucketName),
		Key:    aws.String(objectName),
	}
	var getObjAttrsInput *s3.GetObjectAttributesInput = &s3.GetObjectAttributesInput{
		Bucket:           aws.String(bucketName),
		Key:              aws.String(objectName),
		ObjectAttributes: []types.ObjectAttributes{types.ObjectAttributesEtag},
	}

	versionId, ok := task.VersionIDString()
	if ok {
		getObjAttrsInput.VersionId = &versionId
		getObjInput.VersionId = &versionId
	}

	objAttrs, err := ft.client.GetObjectAttributes(ft.ctx, getObjAttrsInput)
	if err != nil {
		return nil, err
	}

	// If the ETag doesn't match what we have stored, try to find the correct version
	if strings.Trim(*objAttrs.ETag, "\"") != task.Digest {
		if task.VersionId != nil {
			return nil, fmt.Errorf(
				"digest/etag mismatch: etag %s does not match expected digest %s",
				*objAttrs.ETag,
				task.Digest,
			)
		}
		getObjInput, err = ft.getCorrectObjectVersion(
			bucketName,
			objectName,
			task.Digest,
			getObjInput,
		)
		if err != nil {
			return nil, err
		}
	}
	return getObjInput, nil
}

// listObjectsWithPrefix returns a list of all objects in the specified bucket
// that begin with the given prefix.
func (ft *S3FileTransfer) listObjectsWithPrefix(
	bucketName string,
	prefix string,
) ([]*s3.GetObjectInput, error) {
	var objects []*s3.GetObjectInput
	params := &s3.ListObjectsV2Input{
		Bucket: aws.String(bucketName),
		Prefix: aws.String(prefix),
	}
	isTruncated := true
	for isTruncated {
		output, err := ft.client.ListObjectsV2(ft.ctx, params)
		if err != nil {
			return nil, err
		}

		for _, object := range output.Contents {
			objects = append(objects, &s3.GetObjectInput{
				Bucket: aws.String(bucketName),
				Key:    object.Key,
			})
		}

		if output.IsTruncated != nil {
			isTruncated = *output.IsTruncated
		} else {
			isTruncated = false
		}
		if isTruncated {
			params.ContinuationToken = output.NextContinuationToken
		}
	}
	return objects, nil
}

// getCorrectObjectVersion attempts to find the version of an object with
// an ETag that matches the specified digest, and returns the input to
// retrieve that object.
func (ft *S3FileTransfer) getCorrectObjectVersion(
	bucketName string,
	objectName string,
	digest string,
	getObjInput *s3.GetObjectInput,
) (*s3.GetObjectInput, error) {
	params := &s3.ListObjectVersionsInput{
		Bucket: aws.String(bucketName),
		Prefix: aws.String(objectName),
	}
	isTruncated := true
	for isTruncated {
		versions, err := ft.client.ListObjectVersions(ft.ctx, params)
		if err != nil {
			return nil, err
		}
		for _, version := range versions.Versions {
			if strings.Trim(*version.ETag, "\"") == digest {
				getObjInput.Key = aws.String(*version.Key)
				getObjInput.VersionId = version.VersionId
				return getObjInput, nil
			}
		}
		if versions.IsTruncated != nil {
			isTruncated = *versions.IsTruncated
		} else {
			isTruncated = false
		}
		if isTruncated {
			params.KeyMarker = versions.NextKeyMarker
		}
	}
	return nil, fmt.Errorf(
		"digest/etag mismatch: unable to find version with expected digest %s",
		digest,
	)
}

// downloadFiles downloads all of the objects in the specified bucket.
func (ft *S3FileTransfer) downloadFiles(
	rootObjectName string,
	getObjectInputs []*s3.GetObjectInput,
	basePath string,
) error {
	g := new(errgroup.Group)
	g.SetLimit(maxS3Workers)
	for _, input := range getObjectInputs {
		g.Go(func() error {
			objectRelativePath, _ := strings.CutPrefix(*input.Key, rootObjectName)
			localPath := filepath.Join(basePath, filepath.FromSlash(objectRelativePath))
			return ft.downloadFile(input, localPath)
		})
	}

	return g.Wait()
}

// downloadFile downloads the content of an object to the specified path.
func (ft *S3FileTransfer) downloadFile(
	getObjInput *s3.GetObjectInput,
	localPath string,
) error {
	object, err := ft.client.GetObject(ft.ctx, getObjInput)
	if err != nil {
		return err
	}
	defer object.Body.Close()

	return fileutil.CopyReaderToFile(object.Body, localPath)
}

func (ft *S3FileTransfer) formatDownloadError(context string, err error) error {
	return fmt.Errorf("S3FileTransfer: Download: %s: %v", context, err)
}
