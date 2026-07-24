package encodingbench

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestEncodeProducesStableOutput(t *testing.T) {
	dir := t.TempDir()
	require.NoError(t, ExportFixtures(dir))

	manifest, err := LoadManifest(dir)
	require.NoError(t, err)
	require.Equal(t, FixtureSchemaVersion, manifest.SchemaVersion)
	require.NotEmpty(t, manifest.Fixtures)

	committedDir := filepath.Join("testdata")
	committed, err := LoadManifest(committedDir)
	if os.IsNotExist(err) {
		t.Skip("committed testdata/manifest.json not present; run exportfixtures and commit testdata")
	}
	require.NoError(t, err)

	committedByID := make(map[string]FixtureEntry, len(committed.Fixtures))
	for _, entry := range committed.Fixtures {
		committedByID[entry.ID] = entry
	}

	for _, entry := range manifest.Fixtures {
		committedEntry, ok := committedByID[entry.ID]
		require.Truef(t, ok, "missing committed fixture %q", entry.ID)
		require.Equal(t, committedEntry.SHA256Body, entry.SHA256Body, "body hash mismatch for %s", entry.ID)
		require.Equal(t, committedEntry.SHA256Envelope, entry.SHA256Envelope, "envelope hash mismatch for %s", entry.ID)
	}
}
