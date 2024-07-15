package artifacts

import (
	"math"
	"testing"

	"github.com/stretchr/testify/assert"
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
