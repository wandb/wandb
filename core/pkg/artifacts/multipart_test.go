package artifacts

import (
	"crypto/rand"
	"math"
	"os"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestCreateMultiPartRequest_EmptyFile(t *testing.T) {
	// Test with a file size of 0
	tempFile, err := os.CreateTemp("", "test_multipart_*")
	require.NoError(t, err)
	defer os.Remove(tempFile.Name())
	defer tempFile.Close()

	// Returns nil, nil for empty file (and any file that is smaller than 2GB)
	parts, err := createMultiPartRequest(observability.NewNoOpLogger(), tempFile.Name())
	require.NoError(t, err)
	assert.Nil(t, parts)
}

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

func TestComputeMultipartHashes(t *testing.T) {
	// Create a temporary file with 21MB of random data
	tempFile, err := os.CreateTemp("", "test_multipart_*")
	require.NoError(t, err)
	defer os.Remove(tempFile.Name())
	defer tempFile.Close()

	// Write 21MB of random data
	fileSize := int64(21 * 1024 * 1024) // 21MB
	data := make([]byte, fileSize)
	_, err = rand.Read(data)
	require.NoError(t, err)

	_, err = tempFile.Write(data)
	require.NoError(t, err)
	err = tempFile.Close()
	require.NoError(t, err)

	p := tempFile.Name()
	logger := observability.NewNoOpLogger()

	// Invalid chunk size, larger than file, e.g. 22MB
	_, err = computeMultipartHashes(logger, p, fileSize, fileSize+1, 1)
	require.Error(t, err)
	assert.ErrorContains(t, err, "file size is less than chunk size")

	_, err = computeMultipartHashes(logger, p, fileSize, 0, 1)
	require.Error(t, err)
	assert.ErrorContains(t, err, "chunk size is less than 1")

	// Invalid number of workers, less than 1
	_, err = computeMultipartHashes(logger, p, fileSize, fileSize, 0)
	require.Error(t, err)
	assert.ErrorContains(t, err, "number of workers is less than 1")

	// Test with 2MB chunk size
	chunkSize := int64(2 * 1024 * 1024) // 2MB
	numWorkers := 4

	parts, err := computeMultipartHashes(logger, p, fileSize, chunkSize, numWorkers)
	require.NoError(t, err)

	// Should have 11 parts, last part is 1MB
	assert.Len(t, parts, 11)

	// Verify each part has correct part number and non-empty hash
	for i, part := range parts {
		// Server request uses 1-indexed part numbers.
		assert.Equal(t, int64(i+1), part.PartNumber)
		assert.NotEmpty(t, part.HexMD5)
		assert.Len(t, part.HexMD5, 32) // MD5 hex string is 32 characters
	}

	// Verify part numbers are sequential
	for i := 0; i < len(parts)-1; i++ {
		assert.Equal(t, parts[i].PartNumber+1, parts[i+1].PartNumber)
	}
}

func TestComputeMultipartHashesInvalidFile(t *testing.T) {
	logger := observability.NewNoOpLogger()

	// Test with a non-existent file path
	invalidPath := t.TempDir() + "/must_be_404.txt"
	chunkSize := int64(1024 * 1024) // 1MB
	numWorkers := 4
	parts, err := computeMultipartHashes(logger, invalidPath, chunkSize, chunkSize, numWorkers)
	require.Error(t, err)
	assert.Nil(t, parts)
	assert.ErrorContains(t, err, "failed to open file")
	assert.ErrorContains(t, err, invalidPath)
}

func TestSplitHashTasks(t *testing.T) {
	// NOTE: caller of splitTasks guarantees that numWorkers <= numParts
	// and both are positive, so we don't test/handle this case in splitTasks

	t.Run("even distribution", func(t *testing.T) {
		// 6 parts, 2 workers -> each worker gets 3 parts
		tasks := splitHashTasks(6, 2)
		require.Len(t, tasks, 2)

		assert.Equal(t, 0, tasks[0].startPart) // inclusive
		assert.Equal(t, 3, tasks[0].endPart)   // exclusive

		assert.Equal(t, 3, tasks[1].startPart)
		assert.Equal(t, 6, tasks[1].endPart)
	})

	t.Run("uneven distribution", func(t *testing.T) {
		// 11 parts, 3 workers -> 2 workers get 4 parts, 1 worker gets 3 parts
		tasks := splitHashTasks(11, 3)
		require.Len(t, tasks, 3)

		// Worker 0: parts [0 ,4) (4 parts) - large worker
		assert.Equal(t, 0, tasks[0].startPart)
		assert.Equal(t, 4, tasks[0].endPart)

		// Worker 1: parts [4, 8) (4 parts) - large worker
		assert.Equal(t, 4, tasks[1].startPart)
		assert.Equal(t, 8, tasks[1].endPart)

		// Worker 2: parts [8, 11) (3 parts) - small worker
		assert.Equal(t, 8, tasks[2].startPart)
		assert.Equal(t, 11, tasks[2].endPart)
	})

	t.Run("single worker", func(t *testing.T) {
		// 7 parts, 1 worker -> all parts go to the single worker
		tasks := splitHashTasks(7, 1)
		require.Len(t, tasks, 1)

		assert.Equal(t, 0, tasks[0].startPart)
		assert.Equal(t, 7, tasks[0].endPart)
	})
}
