package artifacts

import (
	"crypto/md5"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"io"
	"log/slog"
	"os"
	"path/filepath"

	"github.com/wandb/wandb/core/pkg/utils"
)

const defaultDirPermissions = 0700 // read/write/execute for owner only.

type Cache interface {
	AddFile(path string) (string, error)
	AddFileAndCheckDigest(path string, digest string) error
	RestoreTo(entry ManifestEntry, dst string) bool
	Write(src io.Reader) (string, error)
}

type FileCache struct {
	root string
}

// HashOnlyCache never writes data but still computes and compares hashes.
type HashOnlyCache struct{}

func NewFileCache(cacheDir string) Cache {
	return &FileCache{root: filepath.Join(cacheDir, "artifacts")}
}

func NewHashOnlyCache() Cache {
	return &HashOnlyCache{}
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
	return addFile(c, path)
}

// AddFile computes the base-64 MD5 hash of the file and returns it. It doesn't write.
func (c *HashOnlyCache) AddFile(path string) (string, error) {
	return addFile(c, path)
}

func addFile(c Cache, path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	return c.Write(f)
}

// Link creates a symlink that points a reference with an etag to a file in the cache.
func (c *FileCache) Link(b64md5, ref, etag string) error {
	md5Path, err := c.md5Path(b64md5)
	if err != nil {
		return err
	}
	if exists, _ := utils.FileExists(md5Path); !exists {
		return fmt.Errorf("no cache file with digest %s", b64md5)
	}
	etagPath := c.etagPath(ref, etag)
	if err := os.MkdirAll(filepath.Dir(etagPath), defaultDirPermissions); err != nil {
		return err
	}
	return os.Symlink(md5Path, etagPath)
}

// AddFileAndCheckDigest copies a file into the cache. If a digest is provided, it also
// verifies that the file's MD5 hash matches the digest.
func (c *FileCache) AddFileAndCheckDigest(path string, digest string) error {
	return addFileAndCheckDigest(c, path, digest)
}

func (c *HashOnlyCache) AddFileAndCheckDigest(path string, digest string) error {
	return addFileAndCheckDigest(c, path, digest)
}

func addFileAndCheckDigest(c Cache, path string, digest string) error {
	b64md5, err := c.AddFile(path)
	if err != nil {
		return err
	}
	if digest != "" && digest != b64md5 {
		return fmt.Errorf("file hash mismatch: expected %s, actual %s", digest, b64md5)
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
	var cachePath string
	if entry.Ref != nil {
		cachePath = c.etagPath(*entry.Ref, entry.Digest)
	} else {
		// If the digest is an MD5 hash, check to see if we already have the file.
		b64md5, err := utils.ComputeFileB64MD5(dst)
		if err == nil && b64md5 == entry.Digest {
			return true
		}
		cachePath, err = c.md5Path(entry.Digest)
		if err != nil {
			return false
		}
	}
	return utils.CopyFile(cachePath, dst) == nil
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
	b64md5, err := utils.ComputeFileB64MD5(dst)
	return err == nil && b64md5 == entry.Digest
}

func (c *FileCache) md5Path(b64md5 string) (string, error) {
	hexHash, err := utils.B64ToHex(b64md5)
	if err != nil {
		return "", err
	}
	return filepath.Join(c.root, "obj", "md5", hexHash[:2], hexHash[2:]), nil
}

func (c *FileCache) etagPath(ref, etag string) string {
	byteHash := utils.ComputeSHA256([]byte(ref))
	etagHash := utils.ComputeSHA256([]byte(etag))
	byteHash = append(byteHash, etagHash...)
	hexhash := hex.EncodeToString(utils.ComputeSHA256(byteHash))
	return filepath.Join(c.root, "obj", "etag", hexhash[:2], hexhash[2:])
}

// Write copies the contents of the reader to the cache and returns the B64MD5 cache key.
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
		tmpFile.Close()
		_ = os.Remove(tmpFile.Name())
	}()

	b64md5, err := copyWithHash(src, tmpFile)
	if err != nil {
		return "", err
	}
	dstPath, err := c.md5Path(b64md5)
	if err != nil {
		return "", err
	}
	if exists, _ := utils.FileExists(dstPath); exists {
		return b64md5, nil
	}
	if err := os.MkdirAll(filepath.Dir(dstPath), defaultDirPermissions); err != nil {
		return "", err
	}
	tmpFile.Close()
	if err := os.Rename(tmpFile.Name(), dstPath); err != nil {
		return "", err
	}
	return b64md5, nil
}

// Write computes and returns the B64MD5 cache key. It doesn't write any data.
func (c *HashOnlyCache) Write(src io.Reader) (string, error) {
	return copyWithHash(src, io.Discard)
}

func copyWithHash(src io.Reader, dst io.Writer) (string, error) {
	hasher := md5.New()
	w := io.MultiWriter(dst, hasher)
	_, err := io.Copy(w, src)
	if err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(hasher.Sum(nil)), nil
}
