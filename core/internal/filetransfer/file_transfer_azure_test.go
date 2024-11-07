package filetransfer_test

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"os"
	"testing"

	"github.com/Azure/azure-sdk-for-go/sdk/azcore"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/runtime"
	"github.com/Azure/azure-sdk-for-go/sdk/storage/azblob"
	"github.com/Azure/azure-sdk-for-go/sdk/storage/azblob/blob"
	"github.com/Azure/azure-sdk-for-go/sdk/storage/azblob/container"
	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observability"
)

// mockS3Client mocks the s3 client with the following buckets/objects:
// bucket
// |
// +-- file1.txt (version "0" content: "v0" ETag: "0", version "latest" content: "v1" ETag: "1")
// +-- file2.txt (content: "file2 content" ETag: "file2 etag")

type mockAzureBlob struct {
	Reference string
	Container string
	Name      string
	VersionId string
	ETag      string
	Content   []byte
}

var azureFile1v0 = mockAzureBlob{
	"https://account.blob.core.windows.net/container/file1.txt",
	"container",
	"file1.txt",
	"0",
	"0",
	[]byte("v0"),
}
var azureFile1Latest = mockAzureBlob{
	"https://account.blob.core.windows.net/container/file1.txt",
	"container",
	"file1.txt",
	"latest",
	"1",
	[]byte("v1"),
}
var azureFile2 = mockAzureBlob{
	"https://account.blob.core.windows.net/container/file2.txt",
	"container",
	"file2.txt",
	"latest",
	"file2 etag",
	[]byte("file2 content"),
}

var mockAzureBlobs = []mockAzureBlob{azureFile1v0, azureFile1Latest, azureFile2}

type mockAzureBlobClient struct {
	blob mockAzureBlob
}

func (m mockAzureBlobClient) DownloadFile(ctx context.Context, destination *os.File, options *blob.DownloadFileOptions) (int64, error) {
	return io.Copy(destination, bytes.NewReader(m.blob.Content))
}

func (m mockAzureBlobClient) GetProperties(ctx context.Context, options *blob.GetPropertiesOptions) (blob.GetPropertiesResponse, error) {
	etag := azcore.ETag(fmt.Sprintf("\"%s\"", m.blob.ETag))
	return blob.GetPropertiesResponse{
		ETag: &etag,
	}, nil
}

func (m mockAzureBlobClient) WithVersionID(versionId string) (*mockAzureBlobClient, error) {
	for _, b := range mockAzureBlobs {
		if b.VersionId == versionId && b.Name == m.blob.Name {
			return &mockAzureBlobClient{b}, nil
		}
	}
	return nil, fmt.Errorf("versionId %s not found", versionId)
}

type MockBlobClientWrapper struct {
	client *mockAzureBlobClient
}

func (b *MockBlobClientWrapper) DownloadFile(ctx context.Context, destination *os.File, options *blob.DownloadFileOptions) (int64, error) {
	return b.client.DownloadFile(ctx, destination, options)
}

func (b *MockBlobClientWrapper) GetProperties(ctx context.Context, options *blob.GetPropertiesOptions) (blob.GetPropertiesResponse, error) {
	return b.client.GetProperties(ctx, options)
}

func (b *MockBlobClientWrapper) WithVersionID(versionId string) (filetransfer.AzureBlobClient, error) {
	client, err := b.client.WithVersionID(versionId)
	if err != nil {
		return nil, err
	}
	return &MockBlobClientWrapper{client: client}, nil
}

func mockMore(r container.ListBlobsFlatResponse) bool {
	return false
}

func mockAzureContainerFetcher(_ context.Context, _ *container.ListBlobsFlatResponse) (container.ListBlobsFlatResponse, error) {
	response := container.ListBlobsFlatResponse{
		ListBlobsFlatSegmentResponse: container.ListBlobsFlatSegmentResponse{
			Segment: &container.BlobFlatListSegment{
				BlobItems: []*container.BlobItem{
					{
						Name:      &azureFile1v0.Name,
						VersionID: &azureFile1v0.VersionId,
					},
					{
						Name:      &azureFile1Latest.Name,
						VersionID: &azureFile1Latest.VersionId,
					},
				},
			},
		},
	}
	return response, nil
}

func mockAzureAccountFetcher(_ context.Context, _ *azblob.ListBlobsFlatResponse) (azblob.ListBlobsFlatResponse, error) {
	response := azblob.ListBlobsFlatResponse{
		ListBlobsFlatSegmentResponse: azblob.ListBlobsFlatSegmentResponse{
			Segment: &container.BlobFlatListSegment{
				BlobItems: []*container.BlobItem{
					{
						Name:      &azureFile1Latest.Name,
						VersionID: &azureFile1Latest.VersionId,
					},
					{
						Name:      &azureFile2.Name,
						VersionID: &azureFile2.VersionId,
					},
				},
			},
		},
	}
	return response, nil
}

type mockAzureContainerClient struct{}

func (m mockAzureContainerClient) NewBlobClient(blobName string) filetransfer.AzureBlobClient {
	for _, b := range mockAzureBlobs {
		if b.Name == blobName {
			return &MockBlobClientWrapper{&mockAzureBlobClient{b}}
		}
	}
	return &MockBlobClientWrapper{&mockAzureBlobClient{}}
}
func (m mockAzureContainerClient) NewListBlobsFlatPager(options *container.ListBlobsFlatOptions) *runtime.Pager[container.ListBlobsFlatResponse] {
	pager := runtime.NewPager(runtime.PagingHandler[container.ListBlobsFlatResponse]{
		More:    mockMore,
		Fetcher: mockAzureContainerFetcher,
	})
	return pager
}

type mockAzureAccountClient struct{}

func (m mockAzureAccountClient) DownloadFile(ctx context.Context, containerName string, blobName string, destination *os.File, options *azblob.DownloadFileOptions) (int64, error) {
	for _, b := range mockAzureBlobs {
		if b.Name == blobName && b.Container == containerName && b.VersionId == "latest" {
			return io.Copy(destination, bytes.NewReader(b.Content))
		}
	}
	return 0, fmt.Errorf("blob %s not found", blobName)
}

func (m mockAzureAccountClient) NewListBlobsFlatPager(containerName string, options *azblob.ListBlobsFlatOptions) *runtime.Pager[azblob.ListBlobsFlatResponse] {
	pager := runtime.NewPager(runtime.PagingHandler[azblob.ListBlobsFlatResponse]{
		More:    mockMore,
		Fetcher: mockAzureAccountFetcher,
	})
	return pager
}

func TestAzureFileTransfer_Download(t *testing.T) {
	accountClients := filetransfer.NewAzureClientsMap()
	accountClients.StoreClient("https://account.blob.core.windows.net", mockAzureAccountClient{})

	containerClients := filetransfer.NewAzureClientsMap()
	containerClients.StoreClient("https://account.blob.core.windows.net/container", mockAzureContainerClient{})

	ftFile1 := filetransfer.NewAzureFileTransfer(
		accountClients,
		observability.NewNoOpLogger(),
		filetransfer.NewFileTransferStats(),
		containerClients,
		&MockBlobClientWrapper{&mockAzureBlobClient{azureFile1Latest}},
	)

	ftFile1v0 := filetransfer.NewAzureFileTransfer(
		accountClients,
		observability.NewNoOpLogger(),
		filetransfer.NewFileTransferStats(),
		containerClients,
		&MockBlobClientWrapper{&mockAzureBlobClient{azureFile1v0}},
	)

	ftFile2 := filetransfer.NewAzureFileTransfer(
		accountClients,
		observability.NewNoOpLogger(),
		filetransfer.NewFileTransferStats(),
		containerClients,
		&MockBlobClientWrapper{&mockAzureBlobClient{azureFile2}},
	)

	tests := []struct {
		name            string
		task            *filetransfer.ReferenceArtifactDownloadTask
		contentExpected []byte
		wantErr         bool
		ft              *filetransfer.AzureFileTransfer
	}{
		{
			name: "Returns error if manifest entry reference is not an azure reference",
			task: &filetransfer.ReferenceArtifactDownloadTask{
				FileKind:     filetransfer.RunFileKindArtifact,
				PathOrPrefix: "test-download-file.txt",
				Reference:    "gs://bucket/path/to/object",
			},
			wantErr: true,
			ft:      ftFile1,
		},
		{
			name: "Returns error if manifest entry reference does not exist in azure",
			task: &filetransfer.ReferenceArtifactDownloadTask{
				FileKind:     filetransfer.RunFileKindArtifact,
				PathOrPrefix: "test-download-file.txt",
				Reference:    "https://fake_account.blob.core.windows.net/fake_container/fake_file.txt",
			},
			wantErr: true,
			ft:      ftFile1,
		},
		{
			name: "Downloads expected content when checksum matches (and not versioned)",
			task: &filetransfer.ReferenceArtifactDownloadTask{
				FileKind:     filetransfer.RunFileKindArtifact,
				PathOrPrefix: azureFile2.Name,
				Reference:    azureFile2.Reference,
				Digest:       azureFile2.ETag,
				Size:         100,
			},
			contentExpected: azureFile2.Content,
			wantErr:         false,
			ft:              ftFile2,
		},
		{
			name: "Downloads expected content when checksum and version matches",
			task: &filetransfer.ReferenceArtifactDownloadTask{
				FileKind:     filetransfer.RunFileKindArtifact,
				PathOrPrefix: azureFile1v0.Name,
				Reference:    azureFile1v0.Reference,
				Digest:       azureFile1v0.ETag,
				Size:         100,
				VersionId:    azureFile1v0.VersionId,
			},
			contentExpected: azureFile1v0.Content,
			wantErr:         false,
			ft:              ftFile1v0,
		},
		{
			name: "Returns error when no version has a matching checksum",
			task: &filetransfer.ReferenceArtifactDownloadTask{
				FileKind:     filetransfer.RunFileKindArtifact,
				PathOrPrefix: "test-download-file.txt",
				Reference:    azureFile1v0.Reference,
				Digest:       "fake etag",
				Size:         100,
			},
			wantErr: true,
			ft:      ftFile1,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			defer os.Remove(tt.task.PathOrPrefix)
			err := tt.ft.Download(tt.task)
			if (err != nil) != tt.wantErr {
				t.Errorf("AzureFileTransfer.Download() error = %v, wantErr %v", err, tt.wantErr)
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
		Reference:    "https://account.blob.core.windows.net/container/",
		Digest:       "https://account.blob.core.windows.net/container/",
		Size:         100,
	}
	path1 := "test/file1.txt"
	path2 := "test/file2.txt"
	defer os.Remove(path1)
	defer os.Remove(path2)

	// Performing the download
	err := ftFile1.Download(task)
	assert.NoError(t, err)

	// Read the downloaded file1
	content, err := os.ReadFile(path1)
	assert.NoError(t, err)
	assert.Equal(t, azureFile1Latest.Content, content)

	// Read the downloaded file2
	content, err = os.ReadFile(path2)
	assert.NoError(t, err)
	assert.Equal(t, azureFile2.Content, content)
}
