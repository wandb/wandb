package filetransfer

import (
	"context"
	"fmt"
	"io"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"strings"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
	"github.com/wandb/wandb/core/pkg/observability"
	"golang.org/x/sync/errgroup"
)

var maxS3Workers int = 1000

const S3MinLargeFileSize int64 = 2 << 30

// S3FileTransfer uploads or downloads files to/from s3
type S3FileTransfer struct {
	// client is the HTTP client for the file transfer
	client *s3.Client

	// logger is the logger for the file transfer
	logger *observability.CoreLogger

	// fileTransferStats is used to track upload/download progress
	fileTransferStats FileTransferStats

	ctx context.Context
}

// News3FileTransfer creates a new fileTransfer
func NewS3FileTransfer(
	client *s3.Client,
	logger *observability.CoreLogger,
	fileTransferStats FileTransferStats,
) (*S3FileTransfer, error) {
	ctx := context.TODO()
	if client == nil {
		cfg, err := config.LoadDefaultConfig(ctx)
		if err != nil {
			return nil, err
		}
		client = s3.NewFromConfig(cfg)
	}

	fileTransfer := &S3FileTransfer{
		logger:            logger,
		client:            client,
		fileTransferStats: fileTransferStats,
		ctx:               ctx,
	}
	return fileTransfer, nil
}

// Upload uploads a file to the server
func (ft *S3FileTransfer) Upload(task *ReferenceArtifactUploadTask) error {
	ft.logger.Debug("S3 file transfer: uploading file", "path", task.PathOrPrefix)

	return nil
}

// Download downloads a file from the server
func (ft *S3FileTransfer) Download(task *ReferenceArtifactDownloadTask) error {
	ft.logger.Debug("s3 file transfer: downloading file", "path", task.PathOrPrefix, "ref", task.Reference)

	// Parse the reference path to get the scheme, bucket, and object
	bucketName, rootObjectName, err := parseS3Reference(task.Reference)
	if err != nil {
		return formatS3DownloadError("error parsing reference", err)
	}

	var getObjectInputs []*s3.GetObjectInput
	if task.HasSingleFile() {
		getObjInput, err := ft.getObjectInputFromTask(bucketName, rootObjectName, task)
		if err != nil {
			return formatS3DownloadError("error constructing object input", err)
		}
		getObjectInputs = []*s3.GetObjectInput{getObjInput}
	} else {
		getObjectInputs, err = ft.listObjectsWithPrefix(bucketName, rootObjectName)
		if err != nil {
			return formatS3DownloadError(
				fmt.Sprintf(
					"error getting objects in bucket %s under prefix %s",
					bucketName, rootObjectName,
				),
				err,
			)
		}
	}
	return ft.downloadFiles(bucketName, rootObjectName, getObjectInputs, task.PathOrPrefix)
}

// getObjectFromTask finds the s3 object that matches the versionId and
// digest/ETag specified by the task
func (ft *S3FileTransfer) getObjectInputFromTask(
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
		return nil, formatS3DownloadError("error getting object attributes", err)
	}

	// If the ETag doesn't match what we have stored, try to find the correct version
	if trimQuotes(*objAttrs.ETag) != task.Digest {
		digestMismatchError := fmt.Errorf(
			"digest/etag mismatch: etag %s does not match expected digest %s",
			*objAttrs.ETag,
			task.Digest,
		)
		if task.VersionId != nil {
			return nil, formatS3DownloadError("", digestMismatchError)
		}
		getObjInput, ok = ft.getCorrectObjectVersion(bucketName, objectName, task.Digest, getObjInput)
		if !ok {
			return nil, formatS3DownloadError("", digestMismatchError)
		}
	}
	return getObjInput, nil
}

// listObjectsWithPrefix returns a list of all objects in the specified bucket
// that begin with the given prefix
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
			return nil, formatS3DownloadError("error when retrieving objects", err)
		}

		for _, object := range output.Contents {
			objects = append(objects, &s3.GetObjectInput{
				Bucket: aws.String(bucketName),
				Key:    object.Key,
			})
		}

		isTruncated = *output.IsTruncated
		if isTruncated {
			params.ContinuationToken = output.NextContinuationToken
		}
	}
	return objects, nil
}

// getCorrectObjectVersion attempts to find the version of an object with
// an ETag that matches the specified digest, and returns the input to
// retrieve that object
func (ft *S3FileTransfer) getCorrectObjectVersion(
	bucketName string,
	objectName string,
	digest string,
	getObjInput *s3.GetObjectInput,
) (*s3.GetObjectInput, bool) {
	params := &s3.ListObjectVersionsInput{
		Bucket: aws.String(bucketName),
		Prefix: aws.String(objectName),
	}
	isTruncated := true
	for isTruncated {
		versions, err := ft.client.ListObjectVersions(ft.ctx, params)
		if err != nil {
			return nil, false
		}
		for _, version := range versions.Versions {
			if trimQuotes(*version.ETag) == digest {
				getObjInput.Key = aws.String(*version.Key)
				getObjInput.VersionId = version.VersionId
				return getObjInput, true
			}
		}
		isTruncated = *versions.IsTruncated
		if isTruncated {
			params.KeyMarker = versions.NextKeyMarker
		}
	}
	return nil, false
}

// downloadFiles downloads all of the objects in the specified bucket
func (ft *S3FileTransfer) downloadFiles(
	bucketName string,
	rootObjectName string,
	getObjectInputs []*s3.GetObjectInput,
	basePath string,
) error {
	g := new(errgroup.Group)
	g.SetLimit(maxS3Workers)
	for _, input := range getObjectInputs {
		// TODO: deal with rate limiting- add exponential backoff?
		getObjectInput := input // for closure in goroutine
		g.Go(func() error {
			objectRelativePath, _ := strings.CutPrefix(*getObjectInput.Key, rootObjectName)
			localPath := filepath.Join(basePath, filepath.FromSlash(objectRelativePath))
			err := ft.downloadFile(getObjectInput, localPath)
			if err != nil {
				return formatS3DownloadError("error downloading file", err)
			}
			return nil
		})
	}

	return g.Wait()
}

// downloadFile downloads the content of an object
func (ft *S3FileTransfer) downloadFile(
	getObjInput *s3.GetObjectInput,
	localPath string,
) error {
	object, err := ft.client.GetObject(ft.ctx, getObjInput)
	if err != nil {
		return formatS3DownloadError("error getting object while downloading", err)
	}
	defer object.Body.Close()
	body, err := io.ReadAll(object.Body)
	if err != nil {
		return formatS3DownloadError("error reading object body while downloading", err)
	}

	return writeToFile(localPath, body)
}

// writeToFile writes the content of body to a file at localPath
func writeToFile(localPath string, body []byte) error {
	dir := path.Dir(localPath)

	if err := os.MkdirAll(dir, os.ModePerm); err != nil {
		return formatS3DownloadError("error trying to create local file", err)
	}

	file, err := os.Create(localPath)
	if err != nil {
		return formatS3DownloadError("error creating local file", err)
	}
	defer file.Close()
	_, err = file.Write(body)
	return err
}

// parseS3Reference parses the reference path and returns the bucket name and
// object name.
func parseS3Reference(reference string) (string, string, error) {
	uriParts, err := url.Parse(reference)
	if err != nil {
		return "", "", err
	}
	if uriParts.Scheme != "s3" {
		err := fmt.Errorf("invalid s3 URI %s", reference)
		return "", "", err
	}
	bucketName := uriParts.Host
	objectName := strings.TrimPrefix(uriParts.Path, "/")
	return bucketName, objectName, nil
}

func formatS3DownloadError(context string, err error) error {
	return fmt.Errorf("S3FileTransfer: Download: %s: %v", context, err)
}

func trimQuotes(str string) string {
	return strings.Trim(str, "\"")
}
