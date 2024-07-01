package filetransfer_test

import (
	"testing"

	"cloud.google.com/go/storage"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/pkg/observability"
)

type mockGCSClient struct {
}

func (m *mockGCSClient) Bucket(name string) *storage.BucketHandle {
	return &storage.BucketHandle{}
}

func TestGCSFileTransfer_Download(t *testing.T) {
	mockGCSClient := &mockGCSClient{}

	nonGSReference := "s3://something/something"
	gsReference := "gs://something/something"

	tests := []struct {
		name    string
		task    *filetransfer.Task
		want    string
		wantErr bool
	}{
		{
			name: "Returns error if manifest entry reference is nil",
			task: &filetransfer.Task{
				FileKind: filetransfer.RunFileKindArtifact,
				Type:     filetransfer.DownloadTask,
				Path:     "test-download-file.txt",
			},
			wantErr: true,
		},
		{
			name: "Returns error if manifest entry reference is not a gcs reference",
			task: &filetransfer.Task{
				FileKind:  filetransfer.RunFileKindArtifact,
				Type:      filetransfer.DownloadTask,
				Path:      "test-download-file.txt",
				Reference: &nonGSReference,
			},
			wantErr: true,
		},
		{
			name: "Returns error if gcs reference doesn't exist",
			task: &filetransfer.Task{
				FileKind:  filetransfer.RunFileKindArtifact,
				Type:      filetransfer.DownloadTask,
				Path:      "test-download-file.txt",
				Reference: &gsReference,
				Size:      100,
			},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ft := filetransfer.NewGCSFileTransfer(
				mockGCSClient,
				observability.NewNoOpLogger(),
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
