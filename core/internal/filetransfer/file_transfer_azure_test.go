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
	"github.com/wandb/wandb/core/internal/observabilitytest"
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

func (m mockAzureBlobClient) DownloadFile(
	ctx context.Context,
	destination *os.File,
	options *blob.DownloadFileOptions,
) (int64, error) {
	return io.Copy(destination, bytes.NewReader(m.blob.Content))
}

func (m mockAzureBlobClient) GetProperties(
	ctx context.Context,
	options *blob.GetPropertiesOptions,
) (blob.GetPropertiesResponse, error) {
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

func mockAzureAccountFetcher(
	_ context.Context,
	_ *azblob.ListBlobsFlatResponse,
) (azblob.ListBlobsFlatResponse, error) {
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

func (m mockAzureAccountClient) DownloadFile(
	ctx context.Context,
	containerName string,
	blobName string,
	destination *os.File,
	options *azblob.DownloadFileOptions,
) (int64, error) {
	for _, b := range mockAzureBlobs {
		if b.Name == blobName && b.Container == containerName && b.VersionId == "latest" {
			return io.Copy(destination, bytes.NewReader(b.Content))
		}
	}
	return 0, fmt.Errorf("blob %s not found", blobName)
}

func (m mockAzureAccountClient) NewListBlobsFlatPager(
	containerName string,
	options *azblob.ListBlobsFlatOptions,
) *runtime.Pager[azblob.ListBlobsFlatResponse] {
	pager := runtime.NewPager(runtime.PagingHandler[azblob.ListBlobsFlatResponse]{
		More:    mockMore,
		Fetcher: mockAzureAccountFetcher,
	})
	return pager
}

func mockSetupAccountClient(
	_ string,
	_ *azidentity.DefaultAzureCredential,
) (filetransfer.AzureAccountClient, error) {
	return mockAzureAccountClient{}, nil
}

func TestAzureFileTransfer_Download(t *testing.T) {
	accountClients := filetransfer.NewAzureClientsMap[filetransfer.AzureAccountClient]()
	_, err := accountClients.LoadOrStore(
		"https://account.blob.core.windows.net",
		mockSetupAccountClient,
	)
	assert.NoError(t, err)

	ftFile1 := filetransfer.NewAzureFileTransfer(
		&filetransfer.AzureClientOverrides{
			AccountClients: accountClients,
			BlobClient:     &mockAzureBlobClient{azureFile1Latest},
		},
		observabilitytest.NewTestLogger(t),
		filetransfer.NewFileTransferStats(),
	)

	ftFile1v0 := filetransfer.NewAzureFileTransfer(
		&filetransfer.AzureClientOverrides{
			AccountClients: accountClients,
			BlobClient:     &mockAzureBlobClient{azureFile1v0},
		},
		observabilitytest.NewTestLogger(t),
		filetransfer.NewFileTransferStats(),
	)

	ftFile2 := filetransfer.NewAzureFileTransfer(
		&filetransfer.AzureClientOverrides{
			AccountClients: accountClients,
			BlobClient:     &mockAzureBlobClient{azureFile2},
		},
		observabilitytest.NewTestLogger(t),
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

func (m mockAzureBlockBlobClient) UploadStream(
	ctx context.Context,
	body io.Reader,
	options *blockblob.UploadStreamOptions,
) (blockblob.UploadStreamResponse, error) {
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
		observabilitytest.NewTestLogger(t),
		filetransfer.NewFileTransferStats(),
	)

	// Creating a file to be uploaded
	filename := "test-upload-file.txt"
	err := os.WriteFile(filename, contentExpected, 0o644)
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
		observabilitytest.NewTestLogger(t),
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
		observabilitytest.NewTestLogger(t),
		filetransfer.NewFileTransferStats(),
	)

	// Creating a file to be uploaded
	filename := "test-upload-file.txt"
	err := os.WriteFile(filename, contentExpected, 0o644)
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

// TestAzureFileTransfer_SafeJoinPath_Integration tests that the Azure file transfer
// properly validates paths using SafeJoinPath.
func TestAzureFileTransfer_SafeJoinPath_Integration(t *testing.T) {
	const basePath = "/tmp/downloads"

	tests := []struct {
		name       string
		blobPrefix string
		blobName   string
		basePath   string
		shouldFail bool
	}{
		{
			name:       "legitimate blob in container root",
			blobPrefix: "artifacts/",
			blobName:   "artifacts/model.bin",
			basePath:   basePath,
			shouldFail: false,
		},
		{
			name:       "legitimate nested blob",
			blobPrefix: "artifacts/",
			blobName:   "artifacts/models/v1/weights.bin",
			basePath:   basePath,
			shouldFail: false,
		},
		{
			name:       "malicious blob with path traversal",
			blobPrefix: "artifacts/",
			blobName:   "artifacts/../../../etc/passwd",
			basePath:   basePath,
			shouldFail: true,
		},
		{
			name:       "malicious blob escaping after valid prefix",
			blobPrefix: "data/",
			blobName:   "data/subdir/../../../.ssh/authorized_keys",
			basePath:   basePath,
			shouldFail: true,
		},
		{
			name:       "blob with mismatched prefix containing traversal",
			blobPrefix: "expected/",
			blobName:   "malicious/../../../etc/shadow",
			basePath:   basePath,
			shouldFail: true,
		},
		{
			name:       "blob targeting Windows system files",
			blobPrefix: "data/",
			blobName:   "data/../../../Windows/System32/config/SAM",
			basePath:   "C:\\downloads",
			shouldFail: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Simulate what downloadFiles does: strip prefix and join paths
			objectRelativePath := tt.blobName
			if len(tt.blobName) >= len(tt.blobPrefix) &&
				tt.blobName[:len(tt.blobPrefix)] == tt.blobPrefix {
				objectRelativePath = tt.blobName[len(tt.blobPrefix):]
			}

			_, err := filetransfer.SafeJoinPath(tt.basePath, objectRelativePath)

			if tt.shouldFail {
				assert.Error(t, err, "expected path traversal to be blocked for: %s", tt.blobName)
				assert.ErrorIs(t, err, filetransfer.ErrPathTraversal)
			} else {
				assert.NoError(t, err, "expected legitimate path to be allowed: %s", tt.blobName)
			}
		})
	}
}

// mockAzureAccountClientWithMaliciousBlobs returns blobs with path traversal sequences
type mockAzureAccountClientWithMaliciousBlobs struct {
	maliciousBlobNames []string
}

func (m *mockAzureAccountClientWithMaliciousBlobs) DownloadFile(
	ctx context.Context,
	containerName string,
	blobName string,
	destination *os.File,
	options *azblob.DownloadFileOptions,
) (int64, error) {
	n, err := destination.WriteString("malicious content")
	return int64(n), err
}

func mockMaliciousFetcher(blobNames []string) func(
	context.Context,
	*azblob.ListBlobsFlatResponse,
) (azblob.ListBlobsFlatResponse, error) {
	return func(
		_ context.Context,
		_ *azblob.ListBlobsFlatResponse,
	) (azblob.ListBlobsFlatResponse, error) {
		var blobItems []*container.BlobItem
		for _, name := range blobNames {
			nameCopy := name
			versionID := "latest"
			blobItems = append(blobItems, &container.BlobItem{
				Name:      &nameCopy,
				VersionID: &versionID,
			})
		}
		response := azblob.ListBlobsFlatResponse{
			ListBlobsFlatSegmentResponse: azblob.ListBlobsFlatSegmentResponse{
				Segment: &container.BlobFlatListSegment{
					BlobItems: blobItems,
				},
			},
		}
		return response, nil
	}
}

func (m *mockAzureAccountClientWithMaliciousBlobs) NewListBlobsFlatPager(
	containerName string,
	options *azblob.ListBlobsFlatOptions,
) *runtime.Pager[azblob.ListBlobsFlatResponse] {
	pager := runtime.NewPager(runtime.PagingHandler[azblob.ListBlobsFlatResponse]{
		More:    mockMore,
		Fetcher: mockMaliciousFetcher(m.maliciousBlobNames),
	})
	return pager
}

func mockSetupMaliciousAccountClient(blobNames []string) func(
	string,
	*azidentity.DefaultAzureCredential,
) (filetransfer.AzureAccountClient, error) {
	return func(_ string, _ *azidentity.DefaultAzureCredential) (filetransfer.AzureAccountClient, error) {
		return &mockAzureAccountClientWithMaliciousBlobs{maliciousBlobNames: blobNames}, nil
	}
}

func TestAzureFileTransfer_Download_PathTraversalPrevention(t *testing.T) {
	tests := []struct {
		name               string
		maliciousBlobNames []string
		reference          string
		shouldFail         bool
	}{
		{
			name:               "blocks simple path traversal",
			maliciousBlobNames: []string{"prefix/../../../etc/passwd"},
			reference:          "https://account.blob.core.windows.net/container/prefix/",
			shouldFail:         true,
		},
		{
			name:               "blocks traversal to ssh directory",
			maliciousBlobNames: []string{"artifacts/../../../.ssh/authorized_keys"},
			reference:          "https://account.blob.core.windows.net/container/artifacts/",
			shouldFail:         true,
		},
		{
			name:               "allows legitimate nested path",
			maliciousBlobNames: []string{"prefix/subdir/file.txt"},
			reference:          "https://account.blob.core.windows.net/container/prefix/",
			shouldFail:         false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			accountClients := filetransfer.NewAzureClientsMap[filetransfer.AzureAccountClient]()
			_, err := accountClients.LoadOrStore(
				"https://account.blob.core.windows.net",
				mockSetupMaliciousAccountClient(tt.maliciousBlobNames),
			)
			assert.NoError(t, err)

			ft := filetransfer.NewAzureFileTransfer(
				&filetransfer.AzureClientOverrides{
					AccountClients: accountClients,
				},
				observabilitytest.NewTestLogger(t),
				filetransfer.NewFileTransferStats(),
			)

			tempDir := t.TempDir()

			// Set Digest == Reference to trigger multi-file download path (HasSingleFile() returns false)
			// This is the code path where our path traversal fix is applied
			task := &filetransfer.ReferenceArtifactDownloadTask{
				FileKind:     filetransfer.RunFileKindArtifact,
				PathOrPrefix: tempDir + "/",
				Reference:    tt.reference,
				Digest:       tt.reference, // Digest == Reference triggers listBlobsWithPrefix
				Size:         100,
			}

			err = ft.Download(task)

			if tt.shouldFail {
				assert.Error(t, err, "expected path traversal to be blocked")
				assert.Contains(t, err.Error(), "path traversal",
					"error should mention path traversal")
			} else if err != nil {
				// For legitimate paths, check that there's no path traversal error
				assert.NotContains(t, err.Error(), "path traversal",
					"legitimate path should not trigger path traversal error")
			}
		})
	}
}

// TestAzureFileTransfer_Download_MultipleMaliciousBlobs tests that all malicious
// blob names in a batch are properly rejected.
func TestAzureFileTransfer_Download_MultipleMaliciousBlobs(t *testing.T) {
	maliciousBlobNames := []string{
		"prefix/legitimate.txt",
		"prefix/../../../etc/passwd",
		"prefix/also-legitimate.txt",
		"prefix/../../../.ssh/authorized_keys",
	}

	accountClients := filetransfer.NewAzureClientsMap[filetransfer.AzureAccountClient]()
	_, err := accountClients.LoadOrStore(
		"https://account.blob.core.windows.net",
		mockSetupMaliciousAccountClient(maliciousBlobNames),
	)
	assert.NoError(t, err)

	ft := filetransfer.NewAzureFileTransfer(
		&filetransfer.AzureClientOverrides{
			AccountClients: accountClients,
		},
		observabilitytest.NewTestLogger(t),
		filetransfer.NewFileTransferStats(),
	)

	tempDir := t.TempDir()

	// Set Digest == Reference to trigger multi-file download path (HasSingleFile() returns false)
	reference := "https://account.blob.core.windows.net/container/prefix/"
	task := &filetransfer.ReferenceArtifactDownloadTask{
		FileKind:     filetransfer.RunFileKindArtifact,
		PathOrPrefix: tempDir + "/",
		Reference:    reference,
		Digest:       reference, // Digest == Reference triggers listBlobsWithPrefix
		Size:         100,
	}

	err = ft.Download(task)

	// Should fail because some blobs contain path traversal
	assert.Error(t, err, "expected path traversal to be blocked in batch")
	assert.Contains(t, err.Error(), "path traversal",
		"error should mention path traversal")

	// Verify no files were written outside temp directory
	for _, target := range []string{"/etc/passwd", "/.ssh/authorized_keys"} {
		_, statErr := os.Stat(filepath.Join(tempDir, target))
		assert.True(t, os.IsNotExist(statErr),
			"file should not exist outside temp dir: %s", target)
	}
}
