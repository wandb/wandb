package artifacts

import (
	"context"
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
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
