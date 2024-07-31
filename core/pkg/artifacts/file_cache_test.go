package artifacts

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/pkg/utils"
)

func setupTestEnvironment(t *testing.T) (*FileCache, func()) {
	t.Helper()
	dir, err := os.MkdirTemp("", "wandb_test")
	require.NoError(t, err)
	os.Setenv("WANDB_CACHE_DIR", dir)

	cleanup := func() {
		os.RemoveAll(dir)
		os.Unsetenv("WANDB_CACHE_DIR")
	}

	fc := NewFileCache(UserCacheDir())
	require.Equal(t, fc.(*FileCache).root, filepath.Join(dir, "artifacts"))

	return fc.(*FileCache), cleanup
}

func TestNewFileCache(t *testing.T) {
	_, cleanup := setupTestEnvironment(t)
	defer cleanup()
}

func TestFileCache_Write(t *testing.T) {
	cache, cleanup := setupTestEnvironment(t)
	defer cleanup()

	// Assuming Write works correctly for setup
	data := []byte("test data")
	expectedMd5, err := cache.Write(bytes.NewReader(data))
	require.NoError(t, err)
	assert.Equal(t, utils.ComputeB64MD5(data), expectedMd5)

	path, err := cache.md5Path(expectedMd5)
	require.NoError(t, err)
	require.NotNil(t, path)
	exists, err := utils.FileExists(path)
	require.NoError(t, err)
	require.True(t, exists)
	readData, err := os.ReadFile(path)
	require.NoError(t, err)
	assert.Equal(t, data, readData)
}

func TestHashOnlyCache_Write(t *testing.T) {
	cache := NewHashOnlyCache()
	data := []byte("test data")
	expectedMd5, err := cache.Write(bytes.NewReader(data))
	require.NoError(t, err)
	assert.Equal(t, utils.ComputeB64MD5(data), expectedMd5)
}

func TestFileCache_AddFile(t *testing.T) {
	cache, cleanup := setupTestEnvironment(t)
	defer cleanup()

	srcFile, err := os.CreateTemp("", "source")
	require.NoError(t, err)
	defer os.Remove(srcFile.Name())

	data := []byte("test data")
	_, err = srcFile.Write(data)
	require.NoError(t, err)
	srcFile.Close()

	md5Hash, err := cache.AddFile(srcFile.Name())
	require.NoError(t, err)
	calculatedHash, err := utils.ComputeFileB64MD5(srcFile.Name())
	require.NoError(t, err)
	assert.Equal(t, md5Hash, calculatedHash)
}

func TestHashOnlyCache_AddFile(t *testing.T) {
	cache := NewHashOnlyCache()
	_, err := cache.AddFile("test")
	require.ErrorContains(t, err, "no such file")
}

func TestFileCache_AddFileAndCheckDigest(t *testing.T) {
	cache, cleanup := setupTestEnvironment(t)
	defer cleanup()

	srcFile, err := os.CreateTemp("", "source")
	require.NoError(t, err)
	defer os.Remove(srcFile.Name())

	data := []byte("some data")
	calculatedHash := utils.ComputeB64MD5(data)
	_, err = srcFile.Write(data)
	require.NoError(t, err)
	srcFile.Close()

	err = cache.AddFileAndCheckDigest(srcFile.Name(), calculatedHash)
	require.NoError(t, err)
}

func TestHashOnlyCache_AddFileAndCheckDigest(t *testing.T) {
	cache := NewHashOnlyCache()

	err := cache.AddFileAndCheckDigest("test", "")
	require.ErrorContains(t, err, "no such file")

	srcFile, err := os.CreateTemp("", "source")
	require.NoError(t, err)
	defer os.Remove(srcFile.Name())

	data := []byte("some data")
	calculatedHash := utils.ComputeB64MD5(data)
	_, err = srcFile.Write(data)
	require.NoError(t, err)
	srcFile.Close()

	err = cache.AddFileAndCheckDigest(srcFile.Name(), "invalid")
	require.ErrorContains(t, err, "file hash mismatch")

	err = cache.AddFileAndCheckDigest(srcFile.Name(), calculatedHash)
	require.NoError(t, err)
}

func TestFileCache_Link(t *testing.T) {
	cache, cleanup := setupTestEnvironment(t)
	defer cleanup()

	cacheKey := "test"
	ref := "gs://example-bucket/some/object/path"
	etag := "some-etag"
	err := cache.Link(cacheKey, ref, etag)
	require.ErrorContains(t, err, "no cache file with digest test")

	err = cache.Link("not a valid base-64 MD5 hash", ref, etag)
	require.ErrorContains(t, err, "illegal base64 data")

	cacheKey, err = cache.Write(bytes.NewReader([]byte("test")))
	require.NoError(t, err)
	err = cache.Link(cacheKey, ref, etag)
	require.NoError(t, err)
}

func TestFileCache_RestoreTo(t *testing.T) {
	cache, cleanup := setupTestEnvironment(t)
	defer cleanup()

	// Write some data to the cache
	data := []byte("restore data")
	cacheKey, err := cache.Write(bytes.NewReader(data))
	require.NoError(t, err)

	rootDir := filepath.Join(os.TempDir(), "restore_root")
	defer os.Remove(rootDir)
	localPath := filepath.Join(rootDir, "test", "dir", "restore_target.test")
	manifestEntry := ManifestEntry{
		Digest: cacheKey,
		Size:   12,
	}

	// Restore the cache file to the target path
	assert.True(t, cache.RestoreTo(manifestEntry, localPath))

	// Verify the file exists at the target path and content matches
	restoredData, err := os.ReadFile(localPath)
	require.NoError(t, err)
	assert.Equal(t, data, restoredData)

	// Delete the file from the cache
	internalPath, err := cache.md5Path(cacheKey)
	require.NoError(t, err)
	require.NoError(t, os.Remove(internalPath))

	// Restore again, and verify that it's fine despite not being in the cache.
	assert.True(t, cache.RestoreTo(manifestEntry, localPath))

	// Our HashOnlyCache should also return true, this is important.
	noOpCache := NewHashOnlyCache()
	assert.True(t, noOpCache.RestoreTo(manifestEntry, localPath))

	// Delete the restored file
	require.NoError(t, os.Remove(localPath))

	// Now when we attempt to restore we should fail.
	assert.False(t, cache.RestoreTo(manifestEntry, localPath))

	// And if we give it an invalid manifest entry, it should fail.
	assert.False(t, cache.RestoreTo(ManifestEntry{Digest: "invalid"}, localPath))
}

func TestFileCache_RestoreToReference(t *testing.T) {
	cache, cleanup := setupTestEnvironment(t)
	defer cleanup()

	// Write some data to the cache
	data := []byte("reference data")
	cacheKey, err := cache.Write(bytes.NewReader(data))
	require.NoError(t, err)

	rootDir := filepath.Join(os.TempDir(), "restore_root")
	defer os.Remove(rootDir)
	localPath := filepath.Join(rootDir, "test", "dir", "restore_target.test")
	refPath := "gs://example-bucket/some/object/path"
	manifestEntry := ManifestEntry{
		Digest: "some-etag",
		Ref:    &refPath,
		Size:   14,
	}
	require.NoError(t, cache.Link(cacheKey, refPath, manifestEntry.Digest))

	// Restore the cache file to the target path
	assert.True(t, cache.RestoreTo(manifestEntry, localPath))

	// Verify the file exists at the target path and content matches
	restoredData, err := os.ReadFile(localPath)
	require.NoError(t, err)
	assert.Equal(t, data, restoredData)

	// The HashOnlyCache can't restore reference entries and should fail, even when
	// the file exists in the cache.
	noOpCache := NewHashOnlyCache()
	assert.False(t, noOpCache.RestoreTo(manifestEntry, localPath))
}
