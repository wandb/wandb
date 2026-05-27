package artifacts_test

import (
	"os"
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/pkg/artifacts"
)

type Marshallable struct {
	Junk string
}

func TestUtilFiles(t *testing.T) {
	data := Marshallable{"junk"}
	filename, digest, size, err := artifacts.WriteJSONToTempFileWithMetadata(data, "")
	defer func() {
		_ = os.Remove(filename)
	}()
	assert.Equal(t, "T1eltpgz2/KgyAYJfrs4Sg==", digest)
	assert.Equal(t, int64(15), size)
	assert.FileExists(t, filename)
	assert.Nil(t, err)
}

// TestUtilFiles_FallbackOnBrokenTMPDIR exercises the $TMPDIR-broken recovery
// path: when the OS default temp dir is unwritable, the call should retry
// with the supplied fallbackDir rather than fail.
func TestUtilFiles_FallbackOnBrokenTMPDIR(t *testing.T) {
	missing := t.TempDir() + "/never-created"
	t.Setenv("TMPDIR", missing)
	t.Setenv("TMP", missing)
	t.Setenv("TEMP", missing)

	fallback := t.TempDir()
	data := Marshallable{"junk"}
	filename, _, _, err := artifacts.WriteJSONToTempFileWithMetadata(data, fallback)
	defer func() {
		if filename != "" {
			_ = os.Remove(filename)
		}
	}()

	assert.NoError(t, err)
	assert.FileExists(t, filename)
	assert.True(
		t,
		len(filename) > len(fallback) && filename[:len(fallback)] == fallback,
		"expected temp file under fallback dir %q, got %q",
		fallback,
		filename,
	)
}

// TestUtilFiles_NoFallbackPreservesLegacyError confirms that an empty
// fallbackDir does NOT trigger a retry — preserves the legacy error so we
// don't quietly succeed in a different location than the caller intended.
func TestUtilFiles_NoFallbackPreservesLegacyError(t *testing.T) {
	missing := t.TempDir() + "/never-created"
	t.Setenv("TMPDIR", missing)
	t.Setenv("TMP", missing)
	t.Setenv("TEMP", missing)

	data := Marshallable{"junk"}
	_, _, _, err := artifacts.WriteJSONToTempFileWithMetadata(data, "")
	assert.Error(t, err)
}
