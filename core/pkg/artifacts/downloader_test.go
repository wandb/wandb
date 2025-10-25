package artifacts

import (
	"context"
	"fmt"
	"io"
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/filetransfertest"
	"github.com/wandb/wandb/core/internal/gqlmock"
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
	gqlClient graphql.Client,
	ftm filetransfer.FileTransferManager,
) *ArtifactDownloader {
	downloader := NewArtifactDownloader(
		context.Background(),
		gqlClient,
		ftm,
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
	downloader := getFakeArtifactDownloader(mockGQL, ftm)

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
	downloader := getFakeArtifactDownloader(mockGQL, ftm)

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

func TestGetArtifactManifest(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("ArtifactManifest"),
		`{
			"artifact": {
				"currentManifest": {
					"file": {
						"directUrl": "https://example.com/manifest.json"
					}
				}
			}
		}`,
	)

	ftm := filetransfertest.NewFakeFileTransferManager()
	// Configure custom manifest response
	ftm.DownloadToFunc = func(u string, w io.Writer) error {
		assert.Equal(t, "https://example.com/manifest.json", u)
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
		_, err := w.Write([]byte(manifestJSON))
		return err
	}

	downloader := getFakeArtifactDownloader(mockGQL, ftm)

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

func TestGetArtifactManifest_GraphQLError(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("ArtifactManifest"),
		`{"errors": [{"message": "Artifact not found"}]}`,
	)

	ftm := filetransfertest.NewFakeFileTransferManager()
	downloader := getFakeArtifactDownloader(mockGQL, ftm)

	_, err := downloader.getArtifactManifest(fakeArtifactID)

	require.Error(t, err)
}

func TestGetArtifactManifest_DownloadError(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("ArtifactManifest"),
		`{
			"artifact": {
				"currentManifest": {
					"file": {
						"directUrl": "https://example.com/manifest.json"
					}
				}
			}
		}`,
	)

	ftm := filetransfertest.NewFakeFileTransferManager()
	// Simulate download failure
	ftm.DownloadToFunc = func(u string, w io.Writer) error {
		return fmt.Errorf("network error: connection timeout")
	}

	downloader := getFakeArtifactDownloader(mockGQL, ftm)

	_, err := downloader.getArtifactManifest(fakeArtifactID)

	require.Error(t, err)
	assert.Contains(t, err.Error(), "download artifact manifest failed")
	assert.Contains(t, err.Error(), "network error")
}

func TestGetArtifactManifest_InvalidJSON(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("ArtifactManifest"),
		`{
			"artifact": {
				"currentManifest": {
					"file": {
						"directUrl": "https://example.com/manifest.json"
					}
				}
			}
		}`,
	)

	ftm := filetransfertest.NewFakeFileTransferManager()
	// Return invalid JSON
	ftm.DownloadToFunc = func(u string, w io.Writer) error {
		_, err := w.Write([]byte("not valid json {{{"))
		return err
	}

	downloader := getFakeArtifactDownloader(mockGQL, ftm)

	_, err := downloader.getArtifactManifest(fakeArtifactID)

	require.Error(t, err)
	assert.Contains(t, err.Error(), "decode manifest JSON failed")
}
