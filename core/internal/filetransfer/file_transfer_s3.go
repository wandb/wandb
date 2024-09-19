package filetransfer

import (
	"context"
	"fmt"
	"io"
	"net/url"
	"os"
	"path"
	"strings"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/feature/s3/manager"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
	"github.com/wandb/wandb/core/pkg/observability"
	"golang.org/x/sync/errgroup"
)

var maxWorkers int = 1000

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

		// Create an Amazon S3 service client
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
	ft.logger.Debug("S3 file transfer: uploading file", "path", task.Path)

	return nil
}

// Download downloads a file from the server
func (ft *S3FileTransfer) Download(task *ReferenceArtifactDownloadTask) error {
	ft.logger.Debug("s3 file transfer: downloading file", "path", task.Path, "ref", task.Reference)

	// Parse the reference path to get the scheme, bucket, and object
	bucketName, objectName, err := parseReference(task.Reference)
	if err != nil {
		return formatDownloadError("error parsing reference", err)
	}
	filePath := task.Path

	if task.Digest == task.Reference {
		// If not using checksum, get all objects under the reference
		var objects []types.Object
		params := &s3.ListObjectsV2Input{
			Bucket: aws.String(bucketName),
			Prefix: aws.String(objectName),
		}
		isTruncated := true
		for isTruncated {
			output, err := ft.client.ListObjectsV2(ft.ctx, params)
			if err != nil {
				return formatDownloadError("error when retrieving objects", err)
			}

			objects = append(objects, output.Contents...)

			isTruncated = *output.IsTruncated
			if isTruncated {
				params.ContinuationToken = output.NextContinuationToken
			}
		}
		return ft.DownloadFiles(bucketName, objects, task, objectName)
	} else {
		var getObjInput *s3.GetObjectInput = &s3.GetObjectInput{
			Bucket: aws.String(bucketName),
			Key:    aws.String(objectName),
		}
		var objAttrs *s3.GetObjectAttributesOutput
		if task.VersionId != nil {
			versionId, ok := task.VersionId.(string)
			if !ok {
				return formatDownloadError("error parsing versionId into string", err)
			}
			objAttrs, err = ft.client.GetObjectAttributes(ft.ctx, &s3.GetObjectAttributesInput{
				Bucket:           aws.String(bucketName),
				Key:              aws.String(objectName),
				VersionId:        &versionId,
				ObjectAttributes: []types.ObjectAttributes{types.ObjectAttributesEtag},
			})
			if err != nil {
				return formatDownloadError("error getting object attributes", err)
			}
			getObjInput.VersionId = &versionId
		} else {
			objAttrs, err = ft.client.GetObjectAttributes(ft.ctx, &s3.GetObjectAttributesInput{
				Bucket:           aws.String(bucketName),
				Key:              aws.String(objectName),
				ObjectAttributes: []types.ObjectAttributes{types.ObjectAttributesEtag},
			})
			if err != nil {
				return formatDownloadError("error getting object attributes", err)
			}
		}

		if strings.Trim(*objAttrs.ETag, "\"") != task.Digest {
			if task.VersionId != nil {
				err := fmt.Errorf(
					"digest/etag mismatch: etag %s does not match expected digest %s",
					*objAttrs.ETag,
					task.Digest,
				)
				return formatDownloadError("", err)
			}
			params := &s3.ListObjectVersionsInput{
				Bucket: aws.String(bucketName),
				Prefix: aws.String(objectName),
			}
			isTruncated := true
			found := false
			for isTruncated && !found {
				versions, err := ft.client.ListObjectVersions(ft.ctx, params)
				if err != nil {
					return formatDownloadError("error finding object versions", err)
				}
				for _, version := range versions.Versions {
					if strings.Trim(*version.ETag, "\"") == task.Digest {
						getObjInput.Key = aws.String(*version.Key)
						getObjInput.VersionId = version.VersionId
						found = true
						break
					}
				}
				isTruncated = *versions.IsTruncated
				if isTruncated {
					params.KeyMarker = versions.NextKeyMarker
				}
			}
			if !found {
				err := fmt.Errorf(
					"digest/etag mismatch: etag %s does not match expected digest %s",
					*objAttrs.ETag,
					task.Digest,
				)
				return formatDownloadError("", err)
			}
		}

		err = ft.DownloadFile(getObjInput, task, filePath)
		if err != nil {
			return err
		}
	}
	return nil
}

func (ft *S3FileTransfer) DownloadFiles(
	bucketName string,
	objects []types.Object,
	task *ReferenceArtifactDownloadTask,
	objectName string,
) error {
	g := new(errgroup.Group)
	g.SetLimit(maxWorkers)
	for _, obj := range objects {
		// TODO: deal with rate limiting- add exponential backoff?
		object := obj // for closure in goroutine
		g.Go(func() error {
			filePath := getLocalFilePath(task.Path, *object.Key, objectName)

			getObjInput := &s3.GetObjectInput{
				Bucket: aws.String(bucketName),
				Key:    object.Key,
			}

			if *object.Size >= S3MinLargeFileSize {
				err := ft.DownloadLargeFile(getObjInput, task, filePath)
				if err != nil {
					return formatDownloadError("error downloading large file", err)
				}
			} else {
				err := ft.DownloadFile(getObjInput, task, filePath)
				if err != nil {
					return formatDownloadError("error downloading file", err)
				}
			}
			return nil
		})
	}

	// Wait for all of the go routines to complete and return an error
	// if any errored out
	if err := g.Wait(); err != nil {
		return err
	}
	return nil
}

func (ft *S3FileTransfer) DownloadFile(getObjInput *s3.GetObjectInput, task *ReferenceArtifactDownloadTask, fileName string) error {
	object, err := ft.client.GetObject(ft.ctx, getObjInput)
	if err != nil {
		return formatDownloadError("error getting object while downloading", err)
	}
	defer object.Body.Close()
	body, err := io.ReadAll(object.Body)
	if err != nil {
		return formatDownloadError("error reading object body while downloading", err)
	}

	return ft.WriteToFile(task, fileName, body)
}

func (ft *S3FileTransfer) DownloadLargeFile(getObjInput *s3.GetObjectInput, task *ReferenceArtifactDownloadTask, fileName string) error {
	var partMiBs int64 = 10
	downloader := manager.NewDownloader(ft.client, func(d *manager.Downloader) {
		d.PartSize = partMiBs * 1024 * 1024
	})
	buffer := manager.NewWriteAtBuffer([]byte{})
	_, err := downloader.Download(ft.ctx, buffer, getObjInput)
	if err != nil {
		return formatDownloadError("error downloading large object", err)
	}
	return ft.WriteToFile(task, fileName, buffer.Bytes())
}

func (ft *S3FileTransfer) WriteToFile(task *ReferenceArtifactDownloadTask, fileName string, body []byte) error {
	dir := path.Dir(fileName)

	if err := os.MkdirAll(dir, os.ModePerm); err != nil {
		return formatDownloadError("error trying to create local file", err)
	}

	file, err := os.Create(fileName)
	if err != nil {
		return formatDownloadError("error creating local file", err)
	}
	defer file.Close()
	_, err = file.Write(body)
	return err
}

func getLocalFilePath(taskPath string, fullPath string, pathPrefix string) string {
	ext, _ := strings.CutPrefix(fullPath, pathPrefix)
	localPathEscaped, joinErr := url.JoinPath(taskPath, ext)
	localPath, unescapeErr := url.PathUnescape(localPathEscaped)
	if joinErr != nil || unescapeErr != nil {
		return taskPath + ext
	}
	return localPath
}

// parseReference parses the reference path and returns the bucket name and
// object name.
func parseReference(reference string) (string, string, error) {
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

func formatDownloadError(context string, err error) error {
	return fmt.Errorf("S3FileTransfer: Download: %s: %v", context, err)
}
