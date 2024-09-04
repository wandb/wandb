package wbvalue

import (
	"encoding/json"
	"path/filepath"

	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/pkg/utils"
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
