package artifacts_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/pkg/artifacts"
)

type Marshallable struct {
	Junk string
}

func TestUtilFiles(t *testing.T) {
	dir := t.TempDir()
	data := Marshallable{"junk"}
	filename, digest, size, err := artifacts.WriteJSONToTempFileWithMetadata(data, dir)
	defer func() {
		_ = os.Remove(filename)
	}()
	assert.Nil(t, err)
	assert.Equal(t, "T1eltpgz2/KgyAYJfrs4Sg==", digest)
	assert.Equal(t, int64(15), size)
	assert.FileExists(t, filename)
	assert.True(
		t,
		strings.HasPrefix(filename, dir),
		"expected temp file under dir %q, got %q",
		dir,
		filename,
	)
}

// TestUtilFiles_ErrorsWhenDirMissing confirms we surface an error when the
// supplied dir doesn't exist rather than silently falling back to the OS
// default temp dir — writes go where the caller intended or fail loudly.
func TestUtilFiles_ErrorsWhenDirMissing(t *testing.T) {
	missingDir := filepath.Join(t.TempDir(), "never-created")
	data := Marshallable{"junk"}
	_, _, _, err := artifacts.WriteJSONToTempFileWithMetadata(data, missingDir)
	assert.Error(t, err)
}
