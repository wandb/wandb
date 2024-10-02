package artifacts

import (
	"context"
	"math"
	"testing"

	"github.com/golang/mock/gomock"
	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/filetransfertest"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestGetChunkSize(t *testing.T) {
	defaultChunkSize := int64(100 * 1024 * 1024)

	fileSizes := []int64{
		// Uses the default chunk size
		defaultChunkSize / 100,
		defaultChunkSize,
		defaultChunkSize + 1,
		10000 * defaultChunkSize,
		// Uses the next largest chunk size (+4096)
		10000*defaultChunkSize + 1,
		10000 * (defaultChunkSize + 4096),
		// Uses the next-next largest chunk size (+2*4096)
		10000*(defaultChunkSize+4096) + 1,
	}

	for _, fileSize := range fileSizes {
		chunkSize := getChunkSize(fileSize)
		assert.GreaterOrEqual(t, chunkSize, defaultChunkSize)
		// Chunk size should always be a multiple of 4096.
		assert.True(t, chunkSize%4096 == 0)
		// Chunk size is always sufficient to upload the file in no more than S3MaxParts chunks.
		assert.True(t, chunkSize*S3MaxParts >= fileSize)
		if chunkSize > defaultChunkSize {
			// If chunk size is greater than the default, we should be uploading S3MaxParts chunks.
			chunksUsed := int(math.Ceil(float64(fileSize) / float64(chunkSize)))
			assert.Equal(t, S3MaxParts, chunksUsed)
		}
	}
}

func TestSaveGraphQLRequest(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("InputFields"),
		`{"TypeInfo": {"inputFields": [{"name": "tags"}]}}`,
	)
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("CreateArtifact"),
		`{
			"createArtifact": {
				"artifact": {
					"id": "artifact-id",
					"state": "PENDING"
				}
			}
		}`,
	)
	mockGQL.StubMatchOnce( // first createManifest request
		gqlmock.WithOpName("CreateArtifactManifest"),
		`{"createArtifactManifest": {}}`,
	)
	mockGQL.StubMatchOnce( // second one, before uploading the manifest
		gqlmock.WithOpName("CreateArtifactManifest"),
		`{
			"createArtifactManifest": {
				"artifactManifest": {
					"file": {
						"uploadUrl": "test-url"
					}
				}
			}
		}`,
	)
	ftm := filetransfertest.NewFakeFileTransferManager()
	ftm.ShouldCompleteImmediately = true
	saver := NewArtifactSaveManager(
		observability.NewNoOpLogger(),
		mockGQL,
		ftm,
	)

	result := <-saver.Save(
		context.Background(),
		&spb.ArtifactRecord{
			Entity: "test-entity",
			Manifest: &spb.ArtifactManifest{
				Version: 1,
			},
		},
		0,
		"",
	)

	assert.NoError(t, result.Err)
	requests := mockGQL.AllRequests()
	assert.Len(t, requests, 4)
	createArtifactRequest := requests[1]
	gqlmock.AssertRequest(t,
		gqlmock.WithVariables(
			gqlmock.GQLVar("input.entityName", gomock.Eq("test-entity")),
		),
		createArtifactRequest)
}
