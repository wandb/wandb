package filetransfer_test

import (
	"strings"
	"testing"

	"cloud.google.com/go/storage"
	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observabilitytest"
)

type mockGCSClient struct {
}

func (m *mockGCSClient) Bucket(name string) *storage.BucketHandle {
	return &storage.BucketHandle{}
}

func (m *mockGCSClient) SetRetry(opts ...storage.RetryOption) {
}

func TestGCSFileTransfer_Download(t *testing.T) {
	mockGCSClient := &mockGCSClient{}

	nonGSReference := "s3://something/something"
	gsReference := "gs://something/something"

	tests := []struct {
		name    string
		task    *filetransfer.ReferenceArtifactDownloadTask
		want    string
		wantErr bool
	}{
		{
			name: "Returns error if manifest entry reference is nil",
			task: &filetransfer.ReferenceArtifactDownloadTask{
				FileKind:     filetransfer.RunFileKindArtifact,
				PathOrPrefix: "test-download-file.txt",
			},
			wantErr: true,
		},
		{
			name: "Returns error if manifest entry reference is not a gcs reference",
			task: &filetransfer.ReferenceArtifactDownloadTask{
				FileKind:     filetransfer.RunFileKindArtifact,
				PathOrPrefix: "test-download-file.txt",
				Reference:    nonGSReference,
			},
			wantErr: true,
		},
		{
			name: "Returns error if gcs reference doesn't exist",
			task: &filetransfer.ReferenceArtifactDownloadTask{
				FileKind:     filetransfer.RunFileKindArtifact,
				PathOrPrefix: "test-download-file.txt",
				Reference:    gsReference,
				Size:         100,
			},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ft := filetransfer.NewGCSFileTransfer(
				mockGCSClient,
				observabilitytest.NewTestLogger(t),
				filetransfer.NewFileTransferStats(),
			)
			err := ft.Download(tt.task)
			if (err != nil) != tt.wantErr {
				t.Errorf("GCSStorageHandler.loadPath() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
		})
	}
}

// TestGCSFileTransfer_SafeJoinPath_Integration tests that the SafeJoinPath function
// correctly handles GCS-style object keys with prefix stripping,
// which is how GCS downloads construct local paths.
func TestGCSFileTransfer_SafeJoinPath_Integration(t *testing.T) {
	tests := []struct {
		name       string
		basePath   string
		prefix     string
		objectName string
		wantErr    bool
	}{
		{
			name:       "legitimate object in bucket root",
			basePath:   "/tmp/downloads",
			prefix:     "artifacts/v1/",
			objectName: "artifacts/v1/model.bin",
			wantErr:    false,
		},
		{
			name:       "legitimate nested object",
			basePath:   "/tmp/downloads",
			prefix:     "artifacts/v1/",
			objectName: "artifacts/v1/subdir/data.json",
			wantErr:    false,
		},
		{
			name:       "malicious object with path traversal",
			basePath:   "/tmp/downloads",
			prefix:     "artifacts/v1/",
			objectName: "artifacts/v1/../../../etc/passwd",
			wantErr:    true,
		},
		{
			name:       "malicious object escaping after valid prefix",
			basePath:   "/tmp/downloads",
			prefix:     "artifacts/v1/",
			objectName: "artifacts/v1/subdir/../../.ssh/authorized_keys",
			wantErr:    true,
		},
		{
			name:       "object with mismatched prefix containing traversal",
			basePath:   "/tmp/downloads",
			prefix:     "expected/prefix/",
			objectName: "different/prefix/../../../etc/cron.d/backdoor",
			wantErr:    true,
		},
		{
			name:       "object targeting Windows system files",
			basePath:   "/tmp/downloads",
			prefix:     "artifacts/v1/",
			objectName: "artifacts/v1/../../../Windows/System32/config/SAM",
			wantErr:    true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Simulate how GCS downloadFiles constructs localPath
			objectRelativePath, _ := strings.CutPrefix(tt.objectName, tt.prefix)
			_, err := filetransfer.SafeJoinPath(tt.basePath, objectRelativePath)

			if tt.wantErr {
				assert.Error(t, err, "expected path traversal to be blocked")
				assert.ErrorIs(t, err, filetransfer.ErrPathTraversal)
			} else {
				assert.NoError(t, err, "expected legitimate path to be allowed")
			}
		})
	}
}

// TestGCSFileTransfer_Download_PathTraversalPrevention tests that
// path traversal attacks are blocked when downloading GCS objects.
// This simulates the exact code path in downloadFiles.
func TestGCSFileTransfer_Download_PathTraversalPrevention(t *testing.T) {
	basePath := "/tmp/downloads"
	tests := []struct {
		name           string
		rootObjectName string
		objectNames    []string
		shouldFail     bool
	}{
		{
			name:           "blocks simple path traversal",
			rootObjectName: "artifacts/v1/",
			objectNames:    []string{"artifacts/v1/../../../etc/passwd"},
			shouldFail:     true,
		},
		{
			name:           "blocks traversal to ssh directory",
			rootObjectName: "artifacts/v1/",
			objectNames: []string{
				"artifacts/v1/subdir/../../.ssh/authorized_keys",
			},
			shouldFail: true,
		},
		{
			name:           "allows legitimate nested path",
			rootObjectName: "artifacts/v1/",
			objectNames: []string{
				"artifacts/v1/model.bin",
				"artifacts/v1/subdir/data.json",
			},
			shouldFail: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Simulate the exact path construction from downloadFiles
			for _, objectName := range tt.objectNames {
				objectRelativePath, _ := strings.CutPrefix(
					objectName, tt.rootObjectName,
				)
				_, err := filetransfer.SafeJoinPath(basePath, objectRelativePath)

				if tt.shouldFail {
					assert.Error(
						t, err,
						"expected path traversal to be blocked for: %s", objectName,
					)
					assert.ErrorIs(t, err, filetransfer.ErrPathTraversal)
				} else {
					assert.NoError(
						t, err,
						"expected legitimate path to be allowed: %s", objectName,
					)
				}
			}
		})
	}
}
