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

func TestGetPartSize(t *testing.T) {
	defaultPartSize := int64(100 * 1024 * 1024)

	fileSizes := []int64{
		// Uses the default part size
		defaultPartSize / 100,
		defaultPartSize,
		defaultPartSize + 1,
		10000 * defaultPartSize,
		// Uses the next largest part size (+4096)
		10000*defaultPartSize + 1,
		10000 * (defaultPartSize + 4096),
		// Uses the next-next largest part size (+2*4096)
		10000*(defaultPartSize+4096) + 1,
	}

	for _, fileSize := range fileSizes {
		partSize := getPartSize(fileSize)
		assert.GreaterOrEqual(t, partSize, defaultPartSize)
		// Part size should always be a multiple of 4096.
		assert.Zero(t, partSize%4096)
		// Part size is always sufficient to upload the file in no more than S3MaxParts parts.
		assert.GreaterOrEqual(t, partSize*S3MaxParts, fileSize)
		if partSize > defaultPartSize {
			// If part size is greater than the default, we should be uploading S3MaxParts parts.
			partsUsed := int(math.Ceil(float64(fileSize) / float64(partSize)))
			assert.Equal(t, S3MaxParts, partsUsed)
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

	// Invalid part size, larger than file, e.g. 22MB
	_, err = computeMultipartHashes(logger, p, fileSize, fileSize+1, 1)
	require.Error(t, err)
	assert.ErrorContains(t, err, "file size is less than part size")

	_, err = computeMultipartHashes(logger, p, fileSize, 0, 1)
	require.Error(t, err)
	assert.ErrorContains(t, err, "part size is less than 1")

	// Invalid number of workers, less than 1
	_, err = computeMultipartHashes(logger, p, fileSize, fileSize, 0)
	require.Error(t, err)
	assert.ErrorContains(t, err, "number of workers is less than 1")

	// Test with 2MB part size
	partSize := int64(2 * 1024 * 1024) // 2MB
	numWorkers := 4

	parts, err := computeMultipartHashes(logger, p, fileSize, partSize, numWorkers)
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
	partSize := int64(1024 * 1024) // 1MB
	numWorkers := 4
	parts, err := computeMultipartHashes(logger, invalidPath, partSize, partSize, numWorkers)
	require.Error(t, err)
	assert.Nil(t, parts)
	assert.ErrorContains(t, err, "failed to open file")
	assert.ErrorContains(t, err, invalidPath)
}
