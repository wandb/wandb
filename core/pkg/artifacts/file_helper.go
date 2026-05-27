package artifacts

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/wandb/wandb/core/internal/hashencode"
)

// WriteJSONToTempFileWithMetadata writes the provided data as JSON to a temporary file.
//
// The OS default temp directory (typically $TMPDIR) is tried first to preserve
// legacy behavior. If that fails — e.g. because $TMPDIR points to a missing
// path on HPC setups where the job script never created it — and fallbackDir
// is non-empty, the call is retried with fallbackDir. Pass a wandb-controlled
// location (e.g. an artifact's stagingDir) so manifest writes don't silently
// fail when the host $TMPDIR is broken. An empty fallbackDir disables the
// retry and preserves the original legacy semantics.
//
// Returns the path to the temporary file, the Base64-encoded MD5 digest of the JSON data,
// the size of the file, and an error if something goes wrong during the process.
func WriteJSONToTempFileWithMetadata(
	data any,
	fallbackDir string,
) (filename, digest string, size int64, err error) {
	// Try the OS default temp dir first (legacy behavior). If that errors and
	// the caller supplied a wandb-controlled fallback, retry there.
	f, err := os.CreateTemp("", "tmpfile-")
	if err != nil && fallbackDir != "" {
		f, err = os.CreateTemp(fallbackDir, "tmpfile-")
	}
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
