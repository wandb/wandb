package wbvalue

import (
	"bytes"
	"encoding/json"
	"fmt"
	"image"
	"path/filepath"

	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/pkg/utils"

	// Import image codecs.
	//
	// NOTE: These imports are used for their side-effects.
	_ "image/jpeg"
	_ "image/png"
)

// Image is an image logged to a run.
//
// Images are uploaded as files in the run's media/images/ folder,
// and metadata about them is saved in the run's history.
type Image struct {
	// EncodedData is the image encoded according to Format.
	EncodedData []byte

	// Format is the encoding used for the image.
	//
	// It should be the file extension for the image file as well.
	// Known supported formats include "png", "jpeg", "bmp".
	Format string

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
	config, format, err := image.DecodeConfig(bytes.NewReader(encodedData))

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

	return Image{
		EncodedData: encodedData,
		Format:      format,
		Width:       width,
		Height:      height,
	}, nil
}

// HistoryValueJSON is the image metadata to keep in the run history.
//
// The `filePath` is the run file path to which the image was saved.
func (img Image) HistoryValueJSON(filePath paths.RelativePath) (string, error) {
	bytes, err := json.Marshal(map[string]any{
		"_type":  "image-file",
		"path":   filepath.ToSlash(string(filePath)),
		"sha256": utils.ComputeSHA256(img.EncodedData),
		"format": "png",
		"size":   len(img.EncodedData),
		"width":  img.Width,
		"height": img.Height,
	})

	return string(bytes), err
}
