package artifacts

import (
	"context"
	"crypto/rand"
	"math"
	"os"
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
		true,
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
	gqlmock.AssertVariables(t,
		createArtifactRequest,
		gqlmock.GQLVar("input.entityName", gomock.Eq("test-entity")))
}

func TestComputeMultipartHashes(t *testing.T) {
	// Create a temporary file with 21MB of random data
	tempFile, err := os.CreateTemp("", "test_multipart_*")
	assert.NoError(t, err)
	defer os.Remove(tempFile.Name())
	defer tempFile.Close()

	// Write 21MB of random data
	fileSize := int64(21 * 1024 * 1024) // 21MB
	data := make([]byte, fileSize)
	_, err = rand.Read(data)
	assert.NoError(t, err)

	_, err = tempFile.Write(data)
	assert.NoError(t, err)
	err = tempFile.Close()
	assert.NoError(t, err)

	// Test with 2MB chunk size
	chunkSize := int64(2 * 1024 * 1024) // 2MB
	numWorkers := 4

	parts, err := computeMultipartHashes(tempFile.Name(), chunkSize, numWorkers)
	assert.NoError(t, err)

	// Should have 11 parts, last part is 1MB
	assert.Len(t, parts, 11)

	// Verify each part has correct part number and non-empty hash
	for i, part := range parts {
		assert.Equal(t, int64(i+1), part.PartNumber)
		assert.NotEmpty(t, part.HexMD5)
		assert.Len(t, part.HexMD5, 32) // MD5 hex string is 32 characters
	}

	// Verify part numbers are sequential
	for i := 0; i < len(parts)-1; i++ {
		assert.Equal(t, parts[i].PartNumber+1, parts[i+1].PartNumber)
	}
}

func TestComputeMultipartHashesInvalidPath(t *testing.T) {
	// Test with a non-existent file path
	invalidPath := t.TempDir() + "/must_be_404.txt"
	chunkSize := int64(1024 * 1024) // 1MB
	numWorkers := 4

	parts, err := computeMultipartHashes(invalidPath, chunkSize, numWorkers)

	// Should return an error and nil parts
	assert.Error(t, err)
	assert.Nil(t, parts)

	// Verify the error message contains the expected information
	assert.ErrorContains(t, err, "failed to get file size for path")
	assert.ErrorContains(t, err, invalidPath)
}
