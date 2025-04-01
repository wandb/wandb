package artifacts

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/wandb/wandb/core/internal/hashencode"
)

// WriteJSONToTempFileWithMetadata writes the provided data as JSON to a temporary file.
//
// Returns the path to the temporary file, the Base64-encoded MD5 digest of the JSON data,
// the size of the file, and an error if something goes wrong during the process.
func WriteJSONToTempFileWithMetadata(data any) (filename string, digest string, size int64, err error) {
	// Create a temporary file
	f, err := os.CreateTemp("", "tmpfile-")
	if err != nil {
		return "", "", 0, fmt.Errorf("unable to create temporary file: %w", err)
	}
	defer func() {
		_ = f.Close()
	}()

	// Marshal the data into JSON
	dataJSON, err := json.Marshal(data)
	if err != nil {
		return "", "", 0, fmt.Errorf("failed to marshal data to JSON: %w", err)
	}

	// Write the JSON data to the temporary file
	if _, err := f.Write(dataJSON); err != nil {
		return "", "", 0, fmt.Errorf("failed to write data to file: %w", err)
	}

	// Retrieve file size
	fileInfo, err := f.Stat()
	if err != nil {
		return "", "", 0, fmt.Errorf("failed to stat file: %w", err)
	}
	size = fileInfo.Size()

	// Compute the Base64-encoded MD5 digest of the JSON data
	digest = hashencode.ComputeB64MD5(dataJSON)

	filename = f.Name()

	return filename, digest, size, nil
}
