package wbvalue_test

import (
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/wbvalue"
)

const testPNG2x4 = "" +
	// PNG header
	"\x89PNG\x0D\x0A\x1A\x0A" +
	// Required IHDR chunk
	"\x00\x00\x00\x0DIHDR" + // chunk length, "IHDR" magic
	"\x00\x00\x00\x02" + // image width
	"\x00\x00\x00\x04" + // image height
	"\x01\x00\x00\x00\x00" + // buncha other stuff
	"\x8C\x94\xD3\x94" // CRC-32 of "IHDR" and the chunk data

func TestImageFromData(t *testing.T) {
	data := []byte(testPNG2x4)
	image, err := wbvalue.ImageFromData(2, 4, data)

	require.NoError(t, err)

	assert.Equal(t, "png", image.Format)
	assert.Equal(t, 2, image.Width)
	assert.Equal(t, data, image.EncodedData)
}

func TestImageFormatNotParsable(t *testing.T) {
	data := []byte("not a PNG")
	_, err := wbvalue.ImageFromData(1, 1, data)

	require.ErrorContains(t, err, "failed to parse image format")
}

func TestImageDimensionsNotMatching(t *testing.T) {
	data := []byte(testPNG2x4)
	_, err := wbvalue.ImageFromData(1, 1, data)

	require.ErrorContains(t, err, "expected dimensions (1, 1), but saw (2, 4)")
}

func TestHistoryImageValuesJSON(t *testing.T) {
	out, err := wbvalue.HistoryImageValuesJSON(
		[]paths.RelativePath{
			paths.RelativePath("media/images/abc.png"),
		},
		"png",
		2,
		4,
	)

	require.NoError(t, err)

	var historyJson map[string]any
	err = json.Unmarshal([]byte(out), &historyJson)
	require.NoError(t, err)

	assert.Equal(t, float64(1), historyJson["count"])
	assert.Equal(t, "png", historyJson["format"])
	assert.Equal(t, "images/separated", historyJson["_type"])
	assert.Equal(t, float64(2), historyJson["width"])
	assert.Equal(t, float64(4), historyJson["height"])
	assert.Equal(t, "media/images/abc.png", historyJson["filenames"].([]any)[0])
}
