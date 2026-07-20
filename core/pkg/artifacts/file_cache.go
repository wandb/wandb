package artifacts

import (
	"crypto/md5"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"hash"
	"io"
	"log/slog"
	"os"
	"path/filepath"

	"github.com/zeebo/xxh3"

	"github.com/wandb/wandb/core/internal/fileutil"
	"github.com/wandb/wandb/core/internal/hashencode"
)

const (
	defaultDirPermissions  = 0o777 // read/write/execute for all users.
	defaultFilePermissions = 0o666 // read/write for all users.

	maxFileCacheIOTasks = 16
)

type Cache interface {
	AddFile(path string) (string, error)
	AddFileAndCheckDigest(path string, digest string) error
	RestoreTo(entry ManifestEntry, dst string) bool
	Write(src io.Reader) (string, error)
	WithDigestAlgorithm(algorithm string) Cache
}

type FileCache struct {
	root            string
	fileSemaphore   chan struct{}
	digestAlgorithm string
}

// HashOnlyCache never writes data but still computes and compares hashes.
type HashOnlyCache struct {
	fileSemaphore   chan struct{}
	digestAlgorithm string
}

func NewFileCache(cacheDir string) Cache {
	return &FileCache{
		root:          filepath.Join(cacheDir, "artifacts"),
		fileSemaphore: make(chan struct{}, maxFileCacheIOTasks),
	}
}

func NewHashOnlyCache() Cache {
	return &HashOnlyCache{
		fileSemaphore: make(chan struct{}, maxFileCacheIOTasks),
	}
}

// WithDigestAlgorithm returns a new cache that uses the given algorithm for
// hashing and cache-path lookups. The returned cache shares the same root
// directory and concurrency semaphore as the original.
func (c *FileCache) WithDigestAlgorithm(algorithm string) Cache {
	return &FileCache{
		root:            c.root,
		fileSemaphore:   c.fileSemaphore,
		digestAlgorithm: algorithm,
	}
}

func (c *HashOnlyCache) WithDigestAlgorithm(algorithm string) Cache {
	return &HashOnlyCache{
		fileSemaphore:   c.fileSemaphore,
		digestAlgorithm: algorithm,
	}
}

// UserCacheDir returns the cache directory for the current user.
// In order, the following are checked:
// 1. WANDB_CACHE_DIR environment variable
// 2. Platform-specific default home directory
// 3. ./.wandb-cache/wandb
func UserCacheDir() string {
	dir, found := os.LookupEnv("WANDB_CACHE_DIR")
	if !found {
		userCacheDir, err := os.UserCacheDir()
		if err != nil {
			slog.Error("Unable to find cache directory, using .wandb_cache", "err", err)
			return ".wandb_cache/wandb"
		}
		dir = filepath.Join(userCacheDir, "wandb")
	}
	return dir
}

// AddFile copies a file into the cache and returns the B64MD5 cache key.
func (c *FileCache) AddFile(path string) (string, error) {
	c.fileSemaphore <- struct{}{}
	defer func() { <-c.fileSemaphore }()

	return addFile(c, path)
}

// AddFile computes the base-64 MD5 hash of the file and returns it. It doesn't write.
func (c *HashOnlyCache) AddFile(path string) (string, error) {
	c.fileSemaphore <- struct{}{}
	defer func() { <-c.fileSemaphore }()

	return addFile(c, path)
}

func addFile(c Cache, path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer func() {
		_ = f.Close()
	}()
	return c.Write(f)
}

// Link creates a symlink that points a reference with an etag to a file in the cache.
func (c *FileCache) Link(b64digest, ref, etag string) error {
	cachePath, err := c.digestPath(b64digest)
	if err != nil {
		return err
	}
	if exists, _ := fileutil.FileExists(cachePath); !exists {
		return fmt.Errorf("no cache file with digest %s", b64digest)
	}
	etagPath := c.etagPath(ref, etag)
	if err := os.MkdirAll(filepath.Dir(etagPath), defaultDirPermissions); err != nil {
		return err
	}
	return os.Symlink(cachePath, etagPath)
}

// AddFileAndCheckDigest copies a file into the cache. If a digest is provided, it also
// verifies that the file's hash matches the digest.
func (c *FileCache) AddFileAndCheckDigest(path, digest string) error {
	return addFileAndCheckDigest(c, path, digest)
}

// AddFileAndCheckDigest hashes the file and verifies the digest. It does not
// write any data to disk.
func (c *HashOnlyCache) AddFileAndCheckDigest(path, digest string) error {
	return addFileAndCheckDigest(c, path, digest)
}

func addFileAndCheckDigest(c Cache, path, digest string) error {
	b64digest, err := c.AddFile(path)
	if err != nil {
		return err
	}
	if digest != "" && digest != b64digest {
		return fmt.Errorf("file hash mismatch: expected %s, actual %s", digest, b64digest)
	}
	return nil
}

// RestoreTo tries to restore the file referenced in a manifest entry to the given destination.
//
// The return value is true if the dst path contains the correct file, whether it was
// already there or was restored from the cache; it returns false if the file is not
// present and wasn't able to be restored from the cache.
//
// If the file exists, it will be hashed and overwritten if the hash is different; if
// the hash is correct, RestoreTo leaves it alone and returns true. For reference
// entries we don't know the expected hash and will always overwrite the file.
func (c *FileCache) RestoreTo(entry ManifestEntry, dst string) bool {
	c.fileSemaphore <- struct{}{}
	defer func() { <-c.fileSemaphore }()

	var cachePath string
	if entry.Ref != nil {
		cachePath = c.etagPath(*entry.Ref, entry.Digest)
	} else {
		if c.digestAlgorithm == "MANIFEST_XXH128" {
			b64xxh128, err := hashencode.ComputeFileB64XXH128(dst)
			if err == nil && b64xxh128 == entry.Digest {
				return true
			}
		} else {
			b64md5, err := hashencode.ComputeFileB64MD5(dst)
			if err == nil && b64md5 == entry.Digest {
				return true
			}
		}
		var err error
		cachePath, err = c.digestPath(entry.Digest)
		if err != nil {
			return false
		}
	}

	return fileutil.CopyFile(cachePath, dst) == nil
}

// RestoreTo returns true if the file exists at the destination and its hash matches the digest.
//
// This is the same behavior as FileCache.RestoreTo if the cache is empty, since the
// HashOnlyCache ignores the cache entirely.
//
// We can't check the validity of files based on ETags alone so calling RestoreTo with a
// reference entry always returns false.
func (c *HashOnlyCache) RestoreTo(entry ManifestEntry, dst string) bool {
	if entry.Ref != nil {
		return false
	}

	c.fileSemaphore <- struct{}{}
	defer func() { <-c.fileSemaphore }()

	if c.digestAlgorithm == "MANIFEST_XXH128" {
		b64xxh128, err := hashencode.ComputeFileB64XXH128(dst)
		return err == nil && b64xxh128 == entry.Digest
	}
	b64md5, err := hashencode.ComputeFileB64MD5(dst)
	return err == nil && b64md5 == entry.Digest
}

func (c *FileCache) digestPath(b64digest string) (string, error) {
	hexHash, err := hashencode.B64ToHex(b64digest)
	if err != nil {
		return "", err
	}
	subdir := "md5"
	if c.digestAlgorithm == "MANIFEST_XXH128" {
		subdir = "xxh128"
	}
	return filepath.Join(c.root, "obj", subdir, hexHash[:2], hexHash[2:]), nil
}

func (c *FileCache) etagPath(ref, etag string) string {
	byteHash := hashencode.ComputeSHA256([]byte(ref))
	etagHash := hashencode.ComputeSHA256([]byte(etag))
	byteHash = append(byteHash, etagHash...)
	hexhash := hex.EncodeToString(hashencode.ComputeSHA256(byteHash))
	return filepath.Join(c.root, "obj", "etag", hexhash[:2], hexhash[2:])
}

// Write copies the contents of the reader to the cache and returns the base64 digest.
func (c *FileCache) Write(src io.Reader) (string, error) {
	tmpDir := filepath.Join(c.root, "tmp")
	if err := os.MkdirAll(tmpDir, defaultDirPermissions); err != nil {
		return "", err
	}
	tmpFile, err := os.CreateTemp(tmpDir, "")
	if err != nil {
		return "", err
	}
	defer func() {
		_ = tmpFile.Close()
		_ = os.Remove(tmpFile.Name())
	}()

	b64digest, err := copyWithHash(src, tmpFile, c.digestAlgorithm)
	if err != nil {
		return "", err
	}
	dstPath, err := c.digestPath(b64digest)
	if err != nil {
		return "", err
	}
	if exists, _ := fileutil.FileExists(dstPath); exists {
		return b64digest, nil
	}
	if err := os.MkdirAll(filepath.Dir(dstPath), defaultDirPermissions); err != nil {
		return "", err
	}
	_ = tmpFile.Close()
	if err := os.Rename(tmpFile.Name(), dstPath); err != nil {
		return "", err
	}
	if err := os.Chmod(dstPath, defaultFilePermissions); err != nil {
		return "", err
	}
	return b64digest, nil
}

// Write computes and returns the B64MD5 cache key. It doesn't write any data.
func (c *HashOnlyCache) Write(src io.Reader) (string, error) {
	return copyWithHash(src, io.Discard, c.digestAlgorithm)
}

func copyWithHash(src io.Reader, dst io.Writer, digestAlgorithm string) (string, error) {
	var hasher hash.Hash
	switch digestAlgorithm {
	case "MANIFEST_XXH128":
		hasher = xxh3.New128()
	default:
		hasher = md5.New()
	}
	w := io.MultiWriter(dst, hasher)
	_, err := io.Copy(w, src)
	if err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(hasher.Sum(nil)), nil
}
