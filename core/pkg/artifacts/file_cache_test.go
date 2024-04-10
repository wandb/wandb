package artifacts

import (
	"crypto/md5"
	"encoding/base64"
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

	return NewFileCache(), cleanup
}

func TestNewFileCache(t *testing.T) {
	_, cleanup := setupTestEnvironment(t)
	defer cleanup()

	// Test body is mostly setup verification
}

func TestFileCache_FindMd5(t *testing.T) {
	cache, cleanup := setupTestEnvironment(t)
	defer cleanup()

	// Assuming Write works correctly for setup
	data := []byte("test data")
	expectedMd5, err := cache.Write(data)

	require.NoError(t, err)

	found, err := cache.FindMd5(expectedMd5)
	require.NoError(t, err)
	require.NotNil(t, found)
}

func TestFileCache_FindEtag(t *testing.T) {
	cache, cleanup := setupTestEnvironment(t)
	defer cleanup()

	etag := "testEtag"
	url := "http://example.com"
	data := []byte("test data")
	md5Hash, err := cache.Write(data)
	require.NoError(t, err)

	err = cache.LinkEtag(etag, url, md5Hash)
	require.NoError(t, err)

	found := cache.FindEtag(etag, url)
	require.NotNil(t, found)
}

func TestFileCache_Write(t *testing.T) {
	cache, cleanup := setupTestEnvironment(t)
	defer cleanup()

	data := []byte("test data")
	md5Hash, err := cache.Write(data)
	require.NoError(t, err)
	assert.True(t, utils.VerifyDataHash(data, md5Hash))
}

func TestFileCache_CopyFrom(t *testing.T) {
	cache, cleanup := setupTestEnvironment(t)
	defer cleanup()

	srcFile, err := os.CreateTemp("", "source")
	require.NoError(t, err)
	defer os.Remove(srcFile.Name())

	data := []byte("test data")
	_, err = srcFile.Write(data)
	require.NoError(t, err)
	srcFile.Close()

	md5Hash, err := cache.CopyFrom(srcFile.Name())
	require.NoError(t, err)
	assert.True(t, utils.VerifyFileHash(srcFile.Name(), md5Hash))
}

func TestFileCache_CopyTo(t *testing.T) {
	cache, cleanup := setupTestEnvironment(t)
	defer cleanup()

	// Write some data to the cache
	data := []byte("test data for copy")
	cacheKey, err := cache.Write(data)
	require.NoError(t, err)

	// Get the cache file
	cacheFile, err := cache.FindMd5(cacheKey)
	require.NoError(t, err)
	require.NotNil(t, cacheFile)

	// Define the target path for copying
	targetPath := filepath.Join(os.TempDir(), "does-not-exist", "target_copy.test")
	defer os.RemoveAll(filepath.Dir(targetPath))

	// Copy the cache file to the target path
	err = cacheFile.CopyTo(targetPath)
	require.NoError(t, err)

	// Verify the file exists at the target path
	_, err = os.Stat(targetPath)
	require.NoError(t, err)

	// Verify the content is the same
	copiedData, err := os.ReadFile(targetPath)
	require.NoError(t, err)
	assert.Equal(t, data, copiedData)
}

func TestFileCache_RestoreTo(t *testing.T) {
	cache, cleanup := setupTestEnvironment(t)
	defer cleanup()

	// Write some data to the cache
	data := []byte("restore data")
	cacheKey, err := cache.Write(data)
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

	// Delete the restored file
	require.NoError(t, os.Remove(localPath))

	// Now when we attempt to restore we should fail.
	assert.False(t, cache.RestoreTo(manifestEntry, localPath))
}

func TestFileCache_LinkEtag(t *testing.T) {
	cache, cleanup := setupTestEnvironment(t)
	defer cleanup()

	etag := "testEtag"
	url := "http://example.com"
	data := []byte("test data")
	md5Hash, err := cache.Write(data)
	require.NoError(t, err)

	err = cache.LinkEtag(etag, url, md5Hash)
	require.NoError(t, err)

	// Verify symlink creation
	etagPath, _ := cache.etagPath(etag, url)
	_, err = os.Lstat(etagPath)
	assert.NoError(t, err)
}

func TestCacheWriter_WriteAndClose(t *testing.T) {
	cache, cleanup := setupTestEnvironment(t)
	defer cleanup()

	writer := cache.newCacheWriter()
	data := []byte("test data")
	_, err := writer.Write(data)
	require.NoError(t, err)

	md5Hash, err := writer.close()
	require.NoError(t, err)

	hasher := md5.New()
	hasher.Write(data)
	expectedMd5 := base64.StdEncoding.EncodeToString(hasher.Sum(nil))

	assert.Equal(t, expectedMd5, md5Hash)
}

func TestCacheWriter_B64Md5(t *testing.T) {
	cache, cleanup := setupTestEnvironment(t)
	defer cleanup()

	writer := cache.newCacheWriter()
	data := []byte("test data")
	_, err := writer.Write(data)
	require.NoError(t, err)

	md5Hash := writer.B64Md5()

	hasher := md5.New()
	hasher.Write(data)
	expectedMd5 := base64.StdEncoding.EncodeToString(hasher.Sum(nil))

	assert.Equal(t, expectedMd5, md5Hash)
}
