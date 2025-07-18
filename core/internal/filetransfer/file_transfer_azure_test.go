package filetransfer_test

import (
	"bytes"
	"context"
	"encoding/base64"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"github.com/Azure/azure-sdk-for-go/sdk/azcore"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/runtime"
	"github.com/Azure/azure-sdk-for-go/sdk/azidentity"
	"github.com/Azure/azure-sdk-for-go/sdk/storage/azblob"
	"github.com/Azure/azure-sdk-for-go/sdk/storage/azblob/blob"
	"github.com/Azure/azure-sdk-for-go/sdk/storage/azblob/blockblob"
	"github.com/Azure/azure-sdk-for-go/sdk/storage/azblob/container"
	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observability"
)

// the mockAzureClients mock the azure client with the following containers/blobs:
// account/container
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
	Reference: "https://account.blob.core.windows.net/container/file1.txt",
	Container: "container",
	Name:      "file1.txt",
	VersionId: "0",
	ETag:      "0",
	Content:   []byte("v0"),
}
var azureFile1Latest = mockAzureBlob{
	Reference: "https://account.blob.core.windows.net/container/file1.txt",
	Container: "container",
	Name:      "file1.txt",
	VersionId: "latest",
	ETag:      "1",
	Content:   []byte("v1"),
}
var azureFile2 = mockAzureBlob{
	Reference: "https://account.blob.core.windows.net/container/file2.txt",
	Container: "container",
	Name:      "file2.txt",
	VersionId: "latest",
	ETag:      "file2 etag",
	Content:   []byte("file2 content"),
}

var mockAzureBlobs = []mockAzureBlob{azureFile1v0, azureFile1Latest, azureFile2}

type mockAzureBlobClient struct {
	blob mockAzureBlob
}

func (m mockAzureBlobClient) DownloadFile(ctx context.Context, destination *os.File, options *blob.DownloadFileOptions) (int64, error) {
	return io.Copy(destination, bytes.NewReader(m.blob.Content))
}

func (m mockAzureBlobClient) GetProperties(ctx context.Context, options *blob.GetPropertiesOptions) (blob.GetPropertiesResponse, error) {
	etag := azcore.ETag(fmt.Sprintf("%q", m.blob.ETag))
	return blob.GetPropertiesResponse{
		ETag: &etag,
	}, nil
}

// WithVersionID returns an empty blob client when the versionId matches because we are not testing this path
func (m mockAzureBlobClient) WithVersionID(versionId string) (*blob.Client, error) {
	return &blob.Client{}, nil
}

func mockMore(r container.ListBlobsFlatResponse) bool {
	return false
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

func mockSetupAccountClient(_ string, _ *azidentity.DefaultAzureCredential) (filetransfer.AzureAccountClient, error) {
	return mockAzureAccountClient{}, nil
}

func TestAzureFileTransfer_Download(t *testing.T) {
	accountClients := filetransfer.NewAzureClientsMap[filetransfer.AzureAccountClient]()
	_, err := accountClients.LoadOrStore("https://account.blob.core.windows.net", mockSetupAccountClient)
	assert.NoError(t, err)

	ftFile1 := filetransfer.NewAzureFileTransfer(
		&filetransfer.AzureClientOverrides{
			AccountClients: accountClients,
			BlobClient:     &mockAzureBlobClient{azureFile1Latest},
		},
		observability.NewNoOpLogger(),
		filetransfer.NewFileTransferStats(),
	)

	ftFile1v0 := filetransfer.NewAzureFileTransfer(
		&filetransfer.AzureClientOverrides{
			AccountClients: accountClients,
			BlobClient:     &mockAzureBlobClient{azureFile1v0},
		},
		observability.NewNoOpLogger(),
		filetransfer.NewFileTransferStats(),
	)

	ftFile2 := filetransfer.NewAzureFileTransfer(
		&filetransfer.AzureClientOverrides{
			AccountClients: accountClients,
			BlobClient:     &mockAzureBlobClient{azureFile2},
		},
		observability.NewNoOpLogger(),
		filetransfer.NewFileTransferStats(),
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
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			defer func() {
				_ = os.Remove(tt.task.PathOrPrefix)
			}()
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
	path1 := filepath.Join(task.PathOrPrefix, "file1.txt")
	path2 := filepath.Join(task.PathOrPrefix, "file2.txt")
	defer func() {
		_ = os.Remove(path2)
		_ = os.Remove(path1)
	}()

	// Performing the download
	err = ftFile1.Download(task)
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

type mockAzureBlockBlobClient struct {
	t               *testing.T
	contentExpected []byte
	headers         map[string]string
	shouldFail      bool
}

func (m mockAzureBlockBlobClient) UploadStream(ctx context.Context, body io.Reader, options *blockblob.UploadStreamOptions) (blockblob.UploadStreamResponse, error) {
	if m.shouldFail {
		return blockblob.UploadStreamResponse{}, fmt.Errorf("upload failed")
	}
	bodyBytes, err := io.ReadAll(body)
	assert.NoError(m.t, err)
	assert.Equal(m.t, m.contentExpected, bodyBytes)
	assert.Equal(m.t, *options.HTTPHeaders.BlobContentType, m.headers["Content-Type"])
	md5 := base64.StdEncoding.EncodeToString(options.HTTPHeaders.BlobContentMD5)
	assert.Equal(m.t, md5, m.headers["Content-MD5"])

	return blockblob.UploadStreamResponse{}, nil
}

func TestAzureFileTransfer_Upload(t *testing.T) {
	// Content to be uploaded
	contentExpected := []byte("test content for upload")

	// Headers to be tested
	contentMD5 := base64.StdEncoding.EncodeToString([]byte("test"))
	headers := []string{
		"Content-MD5:" + contentMD5,
		"Content-Type:text/plain",
	}

	mockAzureBlockBlobClient := mockAzureBlockBlobClient{
		t:               t,
		contentExpected: contentExpected,
		headers: map[string]string{
			"Content-MD5":  contentMD5,
			"Content-Type": "text/plain",
		},
		shouldFail: false,
	}

	// Creating a file transfer
	ft := filetransfer.NewAzureFileTransfer(
		&filetransfer.AzureClientOverrides{
			BlockBlobClient: &mockAzureBlockBlobClient,
		},
		observability.NewNoOpLogger(),
		filetransfer.NewFileTransferStats(),
	)

	// Creating a file to be uploaded
	filename := "test-upload-file.txt"
	err := os.WriteFile(filename, contentExpected, 0644)
	assert.NoError(t, err)
	defer func() {
		_ = os.Remove(filename)
	}()

	// Mocking task
	task := &filetransfer.DefaultUploadTask{
		Path:    filename,
		Url:     "https://account.blob.core.windows.net/container/test-upload-file.txt",
		Headers: headers,
	}

	// Performing the upload
	err = ft.Upload(task)
	assert.NoError(t, err)
	assert.Equal(t, task.Response.StatusCode, http.StatusOK)
}

func TestAzureFileTransfer_UploadOffsetChunkOverlong(t *testing.T) {
	entireContent := []byte("test content for upload")

	chunkCheckHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
	})
	server := httptest.NewServer(chunkCheckHandler)

	ft := filetransfer.NewAzureFileTransfer(
		&filetransfer.AzureClientOverrides{
			BlockBlobClient: &mockAzureBlockBlobClient{},
		},
		observability.NewNoOpLogger(),
		filetransfer.NewFileTransferStats(),
	)

	tempFile, err := os.CreateTemp("", "")
	assert.NoError(t, err)
	_, err = tempFile.Write(entireContent)
	assert.NoError(t, err)
	_ = tempFile.Close()
	defer func() {
		_ = os.Remove(tempFile.Name())
	}()

	task := &filetransfer.DefaultUploadTask{
		Path:   tempFile.Name(),
		Url:    server.URL,
		Offset: 17,
		Size:   1000,
	}

	err = ft.Upload(task)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "offset + size exceeds the file size")
}

func TestAzureFileTransfer_UploadClientError(t *testing.T) {
	// According to Azure docs, `uploadStream` returns an error if the connection is closed
	// or the context is cancelled.
	contentExpected := []byte("")
	headers := []string{}

	mockAzureBlockBlobClient := mockAzureBlockBlobClient{
		t:               t,
		contentExpected: contentExpected,
		headers:         map[string]string{},
		shouldFail:      true,
	}

	// Creating a file transfer
	ft := filetransfer.NewAzureFileTransfer(
		&filetransfer.AzureClientOverrides{
			BlockBlobClient: &mockAzureBlockBlobClient,
		},
		observability.NewNoOpLogger(),
		filetransfer.NewFileTransferStats(),
	)

	// Creating a file to be uploaded
	filename := "test-upload-file.txt"
	err := os.WriteFile(filename, contentExpected, 0644)
	assert.NoError(t, err)
	defer func() {
		_ = os.Remove(filename)
	}()

	// Mocking task
	task := &filetransfer.DefaultUploadTask{
		Path:    filename,
		Url:     "https://account.blob.core.windows.net/container/test-upload-file.txt",
		Headers: headers,
	}

	// Performing the upload
	err = ft.Upload(task)
	assert.Error(t, err)
}
