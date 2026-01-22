package artifacts

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/filetransfertest"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observabilitytest"
)

var fakeArtifactID = "fake artifact ID"
var fakeRefPath = "fake/ref/path"

var fakeManifest = Manifest{
	Version:             1,
	StoragePolicyConfig: StoragePolicyConfig{StorageLayout: "V1"},
	Contents: map[string]ManifestEntry{
		"file1": {
			Digest:          "digest1",
			Size:            1,
			BirthArtifactID: &fakeArtifactID,
		},
		"file2": {
			Digest:          "digest2",
			Size:            1,
			BirthArtifactID: &fakeArtifactID,
		},
		"ref": {
			Digest:          "refDigest",
			Size:            1,
			BirthArtifactID: &fakeArtifactID,
			Ref:             &fakeRefPath,
		},
	},
}

var filesResult = `{
	"artifact": {
		"files": {
			"pageInfo": {
				"hasNextPage": false,
				"endCursor": "cursor1"
			},
			"edges": [
				{
					"node": {
						"name": "file1",
						"directUrl": "url1"
					}
				},
				{
					"node": {
						"name": "file2",
						"directUrl": "url2"
					}
				},
				{
					"node": {
						"name": "ref",
						"directUrl": "refUrl"
					}
				}
			]
		}
	}
}`

var noFilesResult = `{
	"artifact": {
		"files": {
			"pageInfo": {
				"hasNextPage": false,
				"endCursor": "cursor"
			},
			"edges": []
		}
	}
}`

var filesByManifestEntriesResult = `{
	"artifact": {
		"filesByManifestEntries": {
			"pageInfo": {
				"hasNextPage": false,
				"endCursor": "cursor1"
			},
			"edges": [
				{
					"node": {
						"name": "file1",
						"directUrl": "url1"
					}
				},
				{
					"node": {
						"name": "file2",
						"directUrl": "url2"
					}
				}
			]
		}
	}
}`

var noFilesByManifestEntriesResult = `{
	"artifact": {
		"filesByManifestEntries": {
			"pageInfo": {
				"hasNextPage": false,
				"endCursor": "cursor1"
			},
			"edges": []
		}
	}
}`

func getFakeArtifactDownloader(
	t *testing.T,
	gqlClient graphql.Client,
	ftm filetransfer.FileTransferManager,
) *ArtifactDownloader {
	downloader := NewArtifactDownloader(
		context.Background(),
		gqlClient,
		ftm,
		observabilitytest.NewTestLogger(t),
		map[string]string{},
		fakeArtifactID,
		"",
		false,
		false,
		"",
	)

	return downloader
}

func TestDownload(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("TypeFields"),
		`{"TypeInfo": {"fields": [{"name": "files"}, {"name": "filesByManifestEntries"}]}}`,
	)

	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("ArtifactFileURLsByManifestEntries"),
		filesByManifestEntriesResult,
	)

	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("ArtifactFileURLsByManifestEntries"),
		noFilesByManifestEntriesResult,
	)

	ftm := filetransfertest.NewFakeFileTransferManager()
	ftm.ShouldCompleteImmediately = true
	downloader := getFakeArtifactDownloader(t, mockGQL, ftm)

	err := downloader.downloadFiles(fakeArtifactID, fakeManifest)

	assert.Nil(t, err)

	addedTasks := ftm.Tasks()
	assert.Len(t, addedTasks, 2)

	addedTasksInfo := []string{addedTasks[0].String(), addedTasks[1].String()}
	assert.Contains(
		t,
		addedTasksInfo,
		`DefaultDownloadTask{FileKind: 2, Path: file1, Name: , Url: url1, Size: 1}`,
	)
	assert.Contains(
		t,
		addedTasksInfo,
		`DefaultDownloadTask{FileKind: 2, Path: file2, Name: , Url: url2, Size: 1}`,
	)
}

func TestDownloadLegacyQuery(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("TypeFields"),
		`{"TypeInfo": {"fields": [{"name": "files"}]}}`,
	)

	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("ArtifactFileURLs"),
		filesResult,
	)

	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("ArtifactFileURLs"),
		noFilesResult,
	)

	ftm := filetransfertest.NewFakeFileTransferManager()
	ftm.ShouldCompleteImmediately = true
	downloader := getFakeArtifactDownloader(t, mockGQL, ftm)

	err := downloader.downloadFiles(fakeArtifactID, fakeManifest)

	assert.Nil(t, err)

	addedTasks := ftm.Tasks()
	assert.Len(t, addedTasks, 2)

	addedTasksInfo := []string{addedTasks[0].String(), addedTasks[1].String()}
	assert.Contains(
		t,
		addedTasksInfo,
		`DefaultDownloadTask{FileKind: 2, Path: file1, Name: , Url: url1, Size: 1}`,
	)
	assert.Contains(
		t,
		addedTasksInfo,
		`DefaultDownloadTask{FileKind: 2, Path: file2, Name: , Url: url2, Size: 1}`,
	)
}

// verifyHeadersInRequest checks that all expected headers are present in the request
func verifyHeadersInRequest(
	t *testing.T,
	r *http.Request,
	expectedHeaders map[string]string,
) {
	t.Helper()
	for key, expectedValue := range expectedHeaders {
		assert.Equal(
			t,
			expectedValue,
			r.Header.Get(key),
			"Header %s should have value %s",
			key,
			expectedValue,
		)
	}
}

func TestGetArtifactManifest_WithExtraHeaders(t *testing.T) {
	manifestJSON := `{
		"version": 1,
		"storagePolicy": "wandb-storage-policy-v1",
		"storagePolicyConfig": {"storageLayout": "V2"},
		"contents": {
			"test.txt": {
				"digest": "abc123",
				"size": 42
			}
		}
	}`

	extraHeaders := map[string]string{
		"X-Custom-Header-1": "value1",
		"X-Custom-Header-2": "value2",
	}

	// Create HTTP test server that verifies headers and returns manifest
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Verify that extra headers are present in the request
		verifyHeadersInRequest(t, r, extraHeaders)

		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(manifestJSON))
	}))
	defer server.Close()

	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("ArtifactManifest"),
		fmt.Sprintf(`{
			"artifact": {
				"currentManifest": {
					"file": {
						"directUrl": "%s"
					}
				}
			}
		}`, server.URL),
	)

	ftm := filetransfertest.NewFakeFileTransferManager()

	// Create downloader with extra headers
	downloader := NewArtifactDownloader(
		context.Background(),
		mockGQL,
		ftm,
		observabilitytest.NewTestLogger(t),
		extraHeaders,
		fakeArtifactID,
		"",
		false,
		false,
		"",
	)

	manifest, err := downloader.getArtifactManifest(fakeArtifactID)

	require.NoError(t, err)
	assert.Equal(t, int32(1), manifest.Version)
	assert.Equal(t, "wandb-storage-policy-v1", manifest.StoragePolicy)
	assert.Equal(t, "V2", manifest.StoragePolicyConfig.StorageLayout)
	assert.Len(t, manifest.Contents, 1)
	assert.Contains(t, manifest.Contents, "test.txt")
	assert.Equal(t, "abc123", manifest.Contents["test.txt"].Digest)
	assert.Equal(t, int64(42), manifest.Contents["test.txt"].Size)
}
