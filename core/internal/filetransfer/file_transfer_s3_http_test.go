//go:build cloud_http

package filetransfer_test

import (
	"bytes"
	"context"
	"errors"
	"io"
	"os"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observabilitytest"
)

// mockS3Client mocks the s3 client with the following buckets/objects:
// bucket
// |
// +-- file1.txt (version "0" content: "v0" ETag: "0", version "latest" content: "v1" ETag: "1")
// +-- file2.txt (content: "file2 content" ETag: "file2 etag")

type mockS3Client struct{}

type mockS3File struct {
	Reference string
	Bucket    string
	Key       string
	VersionId string
	ETag      string
	Content   []byte
}

var file1v0 = mockS3File{
	"s3://bucket/file1.txt",
	"bucket",
	"file1.txt",
	"0",
	"0",
	[]byte("v0"),
}
var file1Latest = mockS3File{
	"s3://bucket/file1.txt",
	"bucket",
	"file1.txt",
	"latest",
	"1",
	[]byte("v1"),
}
var file2 = mockS3File{
	"s3://bucket/file2.txt",
	"bucket",
	"file2.txt",
	"latest",
	"file2 etag",
	[]byte("file2 content"),
}

var mockS3Files = []mockS3File{file1v0, file1Latest, file2}

func (m mockS3Client) GetObject(
	ctx context.Context,
	object filetransfer.S3Object,
) (io.ReadCloser, error) {
	if object.VersionID == "" {
		object.VersionID = "latest"
	}
	for _, file := range mockS3Files {
		if file.Bucket == object.Bucket && file.Key == object.Key &&
			file.VersionId == object.VersionID {
			return io.NopCloser(bytes.NewReader(file.Content)), nil
		}
	}
	return nil, errors.New("object does not exist")
}

func (m mockS3Client) GetObjectETag(
	ctx context.Context,
	object filetransfer.S3Object,
) (string, error) {
	if object.VersionID == "" {
		object.VersionID = "latest"
	}
	for _, file := range mockS3Files {
		if file.Bucket == object.Bucket && file.Key == object.Key &&
			file.VersionId == object.VersionID {
			return file.ETag, nil
		}
	}
	return "", errors.New("object does not exist")
}

func (m mockS3Client) ListObjects(
	ctx context.Context,
	bucket, prefix, token string,
) (filetransfer.S3ObjectPage, error) {
	if bucket != "bucket" {
		return filetransfer.S3ObjectPage{}, errors.New("bucket does not exist")
	}
	var page filetransfer.S3ObjectPage
	for _, file := range mockS3Files {
		if file.Bucket == bucket && strings.HasPrefix(file.Key, prefix) &&
			file.VersionId == "latest" {
			page.Keys = append(page.Keys, file.Key)
		}
	}
	return page, nil
}

func (m mockS3Client) ListVersions(
	ctx context.Context,
	bucket, prefix, keyMarker, versionMarker string,
) (filetransfer.S3VersionPage, error) {
	if bucket != "bucket" {
		return filetransfer.S3VersionPage{}, errors.New("bucket does not exist")
	}
	var page filetransfer.S3VersionPage
	for _, file := range mockS3Files {
		if file.Bucket == bucket && strings.HasPrefix(file.Key, prefix) {
			page.Versions = append(
				page.Versions,
				filetransfer.S3ObjectVersion{
					Key:       file.Key,
					VersionID: file.VersionId,
					ETag:      file.ETag,
				},
			)
		}
	}
	return page, nil
}

func TestS3FileTransfer_Download(t *testing.T) {
	mockS3Client := &mockS3Client{}

	tests := []struct {
		name            string
		task            *filetransfer.ReferenceArtifactDownloadTask
		contentExpected []byte
		wantErr         bool
	}{
		{
			name: "Returns error if manifest entry reference is not an s3 reference",
			task: &filetransfer.ReferenceArtifactDownloadTask{
				FileKind:     filetransfer.RunFileKindArtifact,
				PathOrPrefix: "test-download-file.txt",
				Reference:    "gs://bucket/path/to/object",
			},
			wantErr: true,
		},
		{
			name: "Returns error if manifest entry reference does not exist in s3",
			task: &filetransfer.ReferenceArtifactDownloadTask{
				FileKind:     filetransfer.RunFileKindArtifact,
				PathOrPrefix: "test-download-file.txt",
				Reference:    "s3://bucket/path/to/object",
			},
			wantErr: true,
		},
		{
			name: "Downloads expected content when checksum matches (and not versioned)",
			task: &filetransfer.ReferenceArtifactDownloadTask{
				FileKind:     filetransfer.RunFileKindArtifact,
				PathOrPrefix: file2.Key,
				Reference:    file2.Reference,
				Digest:       file2.ETag,
				Size:         100,
			},
			contentExpected: file2.Content,
			wantErr:         false,
		},
		{
			name: "Downloads expected content when checksum and version matches",
			task: &filetransfer.ReferenceArtifactDownloadTask{
				FileKind:     filetransfer.RunFileKindArtifact,
				PathOrPrefix: file1v0.Key,
				Reference:    file1v0.Reference,
				Digest:       file1v0.ETag,
				Size:         100,
				VersionId:    file1v0.VersionId,
			},
			contentExpected: file1v0.Content,
			wantErr:         false,
		},
		{
			name: "Finds correct version when versionId not passed in",
			task: &filetransfer.ReferenceArtifactDownloadTask{
				FileKind:     filetransfer.RunFileKindArtifact,
				PathOrPrefix: file1v0.Key,
				Reference:    file1v0.Reference,
				Digest:       file1v0.ETag,
				Size:         100,
			},
			contentExpected: file1v0.Content,
			wantErr:         false,
		},
		{
			name: "Returns error when no version has a matching checksum",
			task: &filetransfer.ReferenceArtifactDownloadTask{
				FileKind:     filetransfer.RunFileKindArtifact,
				PathOrPrefix: "test-download-file.txt",
				Reference:    file1v0.Reference,
				Digest:       "fake etag",
				Size:         100,
			},
			wantErr: true,
		},
	}

	ft := filetransfer.NewS3FileTransfer(
		mockS3Client,
		observabilitytest.NewTestLogger(t),
		filetransfer.NewFileTransferStats(),
	)

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			defer func() {
				_ = os.Remove(tt.task.PathOrPrefix)
			}()
			err := ft.Download(tt.task)
			if (err != nil) != tt.wantErr {
				t.Errorf("S3StorageHandler.loadPath() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			// if we expected an error, continue without reading file
			if err != nil {
				return
			}

			// Read the downloaded file
			content, err := os.ReadFile(tt.task.PathOrPrefix)
			if err != nil {
				t.Errorf("unable to read downloaded file at path %v", tt.task.PathOrPrefix)
				return
			}
			assert.Equal(t, tt.contentExpected, content)
		})
	}

	// test checksum false downloads all items under path
	task := &filetransfer.ReferenceArtifactDownloadTask{
		FileKind:     filetransfer.RunFileKindArtifact,
		PathOrPrefix: "test/",
		Reference:    "s3://bucket/",
		Digest:       "s3://bucket/",
		Size:         100,
	}
	path1 := "test/file1.txt"
	path2 := "test/file2.txt"
	defer func() {
		_ = os.Remove(path2)
		_ = os.Remove(path1)
	}()

	// Performing the download
	err := ft.Download(task)
	assert.NoError(t, err)

	// Read the downloaded file1
	content, err := os.ReadFile(path1)
	assert.NoError(t, err)
	assert.Equal(t, file1Latest.Content, content)

	// Read the downloaded file2
	content, err = os.ReadFile(path2)
	assert.NoError(t, err)
	assert.Equal(t, file2.Content, content)
}
