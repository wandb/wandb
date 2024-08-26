package artifacts

import (
	"bufio"
	"compress/gzip"
	"encoding/json"
	"os"
	"testing"

	"github.com/stretchr/testify/assert"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestNewManifestFromProto(t *testing.T) {
	proto := &spb.ArtifactManifest{
		Version:       1,
		StoragePolicy: "policy",
		Contents: []*spb.ArtifactManifestEntry{
			{
				Path:   "path1",
				Digest: "digest1",
				Size:   123,
				Extra: []*spb.ExtraItem{
					{Key: "key1", ValueJson: `"value1"`},
				},
			},
		},
	}

	manifest, err := NewManifestFromProto(proto)
	assert.NoError(t, err)
	assert.Equal(t, proto.Version, manifest.Version)
	assert.Equal(t, proto.StoragePolicy, manifest.StoragePolicy)
	assert.Equal(t, "value1", manifest.Contents["path1"].Extra["key1"])
}

func TestNewManifestFromProto_InvalidManifestFilePath(t *testing.T) {
	proto := &spb.ArtifactManifest{
		Version:          1,
		StoragePolicy:    "policy",
		ManifestFilePath: "invalid/path/to/manifest.gz",
	}

	manifest, err := NewManifestFromProto(proto)
	assert.Error(t, err)
	assert.Empty(t, manifest.Contents)
}

func TestManifestContentsFromFile_MissingPath(t *testing.T) {
	// Create a temporary gzipped file with manifest contents missing the "path" field
	tmpFile, err := os.CreateTemp("", "manifest-*.jl.gz")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())

	gzWriter := gzip.NewWriter(tmpFile)
	writer := bufio.NewWriter(gzWriter)
	entryJson, _ := json.Marshal(map[string]any{
		"digest": "digest1",
		"size":   123,
		"extra":  map[string]any{"key1": "value1"},
	})
	_, err = writer.Write(entryJson)
	assert.NoError(t, err)
	writer.Flush()
	gzWriter.Close()
	tmpFile.Close()

	_, err = ManifestContentsFromFile(tmpFile.Name())
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "record missing 'path' key or not a string")
}

func TestManifestContentsFromFile_MissingDigest(t *testing.T) {
	// Create a temporary gzipped file with manifest contents missing the "digest" field
	tmpFile, err := os.CreateTemp("", "manifest-*.jl.gz")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())

	gzWriter := gzip.NewWriter(tmpFile)
	writer := bufio.NewWriter(gzWriter)
	entryJson, _ := json.Marshal(map[string]any{
		"path":  "path1",
		"size":  123,
		"extra": map[string]any{"key1": "value1"},
	})
	_, err = writer.Write(entryJson)
	assert.NoError(t, err)
	writer.Flush()
	gzWriter.Close()
	tmpFile.Close()

	_, err = ManifestContentsFromFile(tmpFile.Name())
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "record missing 'digest' key or not a string")
}

func TestManifestContentsFromFile(t *testing.T) {
	// Create a temporary gzipped file with manifest contents
	tmpFile, err := os.CreateTemp("", "manifest-*.jl.gz")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())

	gzWriter := gzip.NewWriter(tmpFile)
	writer := bufio.NewWriter(gzWriter)
	entry1 := map[string]any{
		"path":   "path1",
		"digest": "digest1",
		"size":   int64(123),
		// JSON is lossy w.r.t. numbers, so 65 (int) becomes 65.0 (float64)
		"extra":           map[string]any{"key1": "value1", "key2": 65.0},
		"local_path":      "local/path1",
		"birthArtifactID": "birthArtifactID1",
	}
	entryJson, _ := json.Marshal(entry1)
	_, err = writer.Write(entryJson)
	assert.NoError(t, err)
	err = writer.WriteByte('\n')
	assert.NoError(t, err)
	entry2 := map[string]any{
		"path":       "path2",
		"digest":     "etag1",
		"ref":        "local/path2",
		"skip_cache": true,
	}
	entryJson, _ = json.Marshal(entry2)
	_, err = writer.Write(entryJson)
	assert.NoError(t, err)
	err = writer.WriteByte('\n')
	assert.NoError(t, err)
	writer.Flush()
	gzWriter.Close()
	tmpFile.Close()

	contents, err := ManifestContentsFromFile(tmpFile.Name())
	assert.NoError(t, err)
	assert.Equal(t, entry1["digest"], contents["path1"].Digest)
	assert.Equal(t, entry1["size"], contents["path1"].Size)
	assert.Nil(t, contents["path1"].Ref)
	assert.Equal(t, entry1["extra"], contents["path1"].Extra)
	assert.Equal(t, entry1["local_path"], *contents["path1"].LocalPath)
	assert.Equal(t, entry1["birthArtifactID"], *contents["path1"].BirthArtifactID)
	assert.False(t, contents["path1"].SkipCache)

	assert.Equal(t, entry2["digest"], contents["path2"].Digest)
	assert.Equal(t, int64(0), contents["path2"].Size)
	assert.Equal(t, entry2["ref"], *contents["path2"].Ref)
	assert.Equal(t, map[string]interface{}{}, contents["path2"].Extra)
	assert.Nil(t, contents["path2"].LocalPath)
	assert.Nil(t, contents["path2"].BirthArtifactID)
	assert.True(t, contents["path2"].SkipCache)
}

func TestManifest_WriteToFile(t *testing.T) {
	manifest := Manifest{
		Version:       1,
		StoragePolicy: "policy",
		Contents: map[string]ManifestEntry{
			"path1": {
				Digest: "digest1",
				Size:   123,
				Extra:  map[string]any{"key1": "value1"},
			},
		},
	}

	filename, digest, size, err := manifest.WriteToFile()
	assert.NoError(t, err)
	assert.NotEmpty(t, filename)
	assert.NotEmpty(t, digest)
	assert.NotZero(t, size)
	defer os.Remove(filename)
}

func TestManifest_GetManifestEntryFromArtifactFilePath(t *testing.T) {
	manifest := Manifest{
		Contents: map[string]ManifestEntry{
			"path1": {
				Digest: "digest1",
				Size:   123,
				Extra:  map[string]any{"key1": "value1"},
			},
		},
	}

	entry, err := manifest.GetManifestEntryFromArtifactFilePath("path1")
	assert.NoError(t, err)
	assert.Equal(t, "digest1", entry.Digest)
	assert.Equal(t, int64(123), entry.Size)

	_, err = manifest.GetManifestEntryFromArtifactFilePath("nonexistent")
	assert.Error(t, err)
}
