package server

import (
	"fmt"
	"os"
	"path/filepath"

	"strconv"

	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"image"
	"image/color"
	"image/png"

	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/pkg/service"
)


func createPNG(data []byte, width, height int, filesPath string, imagePath string) (string, string, int, error) {
	// Create a new RGBA image
	img := image.NewRGBA(image.Rect(0, 0, width, height))

	// Index for accessing the byte array
	idx := 0

	// Populate the image with pixels
	for y := 0; y < height; y++ {
		for x := 0; x < width; x++ {
			r := data[idx]
			g := data[idx+1]
			b := data[idx+2]
			img.SetRGBA(x, y, color.RGBA{R: r, G: g, B: b, A: 0xff})
			idx += 3 // Move to the next pixel (skip 3 bytes)
		}
	}

	// Create a buffer to write our PNG to
	var buf bytes.Buffer

	// Encode the image to the buffer
	if err := png.Encode(&buf, img); err != nil {
		return "", "", 0, err
	}

	// Compute SHA256 of the buffer
	hasher := sha256.New()
	hasher.Write(buf.Bytes())
	hash := hex.EncodeToString(hasher.Sum(nil))

	// Compute file size
	size := buf.Len()

	imagePath = fmt.Sprintf("%s_%s.png", imagePath, hash[:20])
	outputPath := filepath.Join(filesPath, imagePath)

	// Ensure all directories exist
	dirPath := filepath.Dir(outputPath)
	if err := os.MkdirAll(dirPath, 0755); err != nil {
		return "", "", 0, err
	}

	// Write the buffer to a file
	if err := os.WriteFile(outputPath, buf.Bytes(), 0644); err != nil {
		return "", "", 0, err
	}

	return imagePath, hash, size, nil
}

type Media struct {
	Type   string `json:"_type"`
	Format string `json:"format"`
	Height int    `json:"height"`
	Width  int    `json:"width"`
	Path   string `json:"path"`
	Sha256 string `json:"sha256"`
	Size   int    `json:"size"`
}

// dataValueConvert processes a "DataValue" history record and converts to value_json record
func dataValueConvert(hrecord *service.HistoryRecord, filesPath string) (*service.HistoryRecord, []string) {
	hrecordNew := &service.HistoryRecord{
		Step: hrecord.Step,
	}
	hFiles := []string{}
	for _, item := range hrecord.Item {
		if item.ValueData != nil {
			hItem := &service.HistoryItem{Key: item.Key}
			switch value := item.ValueData.DataType.(type) {
			case *service.DataValue_ValueInt:
				hItem.ValueJson = strconv.FormatInt(value.ValueInt, 10)
			case *service.DataValue_ValueDouble:
				hItem.ValueJson = strconv.FormatFloat(value.ValueDouble, 'E', -1, 64)
			case *service.DataValue_ValueString:
				hItem.ValueJson = fmt.Sprintf(`"%s"`, value.ValueString)
			case *service.DataValue_ValueTensor:
				// fmt.Printf("GOT TENSOR %+v\n", value.ValueTensor)
				imageBase := fmt.Sprintf("%s_%d", item.Key, hrecord.Step.Num)
				imagePath := filepath.Join("media", "images", imageBase)
				shape := value.ValueTensor.Shape
				height := int(shape[0])
				width := int(shape[1])
				// FIXME: make sure channels is 3 for now
				// FIXME: we only handle dtype uint8 also
				fname, hash, size, err := createPNG(value.ValueTensor.TensorContent, height, width, filesPath, imagePath)
				if err != nil {
					fmt.Printf("GOT err %+v\n", err)
				}
				hFiles = append(hFiles, fname)
				media := Media{
					Type:   "image-file",
					Format: "png",
					Height: height,
					Width:  width,
					Size:   size,
					Sha256: hash,
					Path:   fname,
				}
				jsonString, err := simplejsonext.Marshal(media)
				if err != nil {
					fmt.Printf("GOT err %+v\n", err)
				}
				// fmt.Printf("GOT::: %+v %+v %+v %+v\n", string(jsonString), fname, hash, size)
				hItem.ValueJson = string(jsonString)
			}
			hrecordNew.Item = append(hrecordNew.Item, hItem)
		} else {
			hrecordNew.Item = append(hrecordNew.Item, item)
		}
	}
	return hrecordNew, hFiles
}
