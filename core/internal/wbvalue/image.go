package wbvalue

import (
	"bytes"
	"encoding/json"
	"fmt"
	"image"
	"path/filepath"
	"slices"

	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/pkg/utils"

	// Import image codecs.
	_ "image/jpeg"
	"image/png"
)

// Image is an image logged to a run.
//
// Images are uploaded as files in the run's media/images/ folder,
// and metadata about them is saved in the run's history.
type Image struct {
	// PNG is the PNG encoding of the image.
	PNG []byte

	// Width is the image's width in pixels.
	Width int

	// Height is the image's height in pixels.
	Height int
}

// ImageFromData returns an Image from encoded data.
func ImageFromData(
	width int,
	height int,
	encodedData []byte,
) (Image, error) {
	var pngData []byte

	// Special case for PNG data which we can send directly.
	if len(encodedData) >= 8 && slices.Equal(
		encodedData[:8],
		[]byte{0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A},
	) {
		pngData = encodedData
	} else {
		config, _, err := image.DecodeConfig(bytes.NewReader(encodedData))

		if err != nil {
			return Image{}, fmt.Errorf("failed to parse image format: %v", err)
		}
		if config.Height != height || config.Width != width {
			return Image{}, fmt.Errorf(
				"expected dimensions (%d, %d), but saw (%d, %d)",
				width, height,
				config.Width, config.Height,
			)
		}

		img, _, err := image.Decode(bytes.NewReader(encodedData))
		if err != nil {
			return Image{}, fmt.Errorf("failed to decode image: %v", err)
		}

		pngDataBuf := bytes.Buffer{}
		if err = png.Encode(&pngDataBuf, img); err != nil {
			return Image{}, fmt.Errorf("failed to encode png: %v", err)
		}

		pngData = pngDataBuf.Bytes()
	}

	return Image{
		PNG:    pngData,
		Width:  width,
		Height: height,
	}, nil
}

// HistoryValueJSON is the image metadata to keep in the run history.
//
// The `filePath` is the run file path to which the image was saved.
func (img Image) HistoryValueJSON(filePath paths.RelativePath) (string, error) {
	bytes, err := json.Marshal(map[string]any{
		"_type":  "image-file",
		"path":   filepath.ToSlash(string(filePath)),
		"sha256": utils.ComputeSHA256(img.PNG),
		"format": "png",
		"size":   len(img.PNG),
		"width":  img.Width,
		"height": img.Height,
	})

	return string(bytes), err
}
