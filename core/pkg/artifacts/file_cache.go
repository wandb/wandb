package artifacts

import (
	"crypto/md5"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"

	atomicfile "github.com/natefinch/atomic"
	"github.com/wandb/wandb/core/pkg/utils"
)

type FileCache struct {
	root string
}

func NewFileCache() *FileCache {
	dir, found := os.LookupEnv("WANDB_CACHE_DIR")
	if !found {
		userCacheDir, err := os.UserCacheDir()
		if err != nil {
			return nil
		}
		dir = filepath.Join(userCacheDir, "wandb")
	}
	return &FileCache{root: filepath.Join(dir, "artifacts")}
}

// Copy a file into the cache and return the B64MD5 cache key.
func (c *FileCache) AddFile(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	return c.Write(f)
}

// Try to restore the file referenced in a manifest entry to the given destination.
//
// Returns true if the file is already there or is restored successfully.
//
// If the file exists, it will be hashed and overwritten if the hash is different.
func (c *FileCache) RestoreTo(entry ManifestEntry, dst string) bool {
	exists, _ := DeleteInvalid(dst, entry.Digest)
	if exists {
		return true
	}
	cachePath := c.pathTo(entry.Digest)
	if cachePath == nil {
		return false
	}
	// TODO (hugh): should we set the LocalPath in the entry to the dst?
	return utils.CopyFile(*cachePath, dst) == nil
}

// Given the hash of a file return the base64 encoding and the internal cache path.
func (c *FileCache) keyAndPath(hash []byte) (b64md5 string, cachePath string) {
	b64md5 = base64.StdEncoding.EncodeToString(hash)
	hexHash := hex.EncodeToString(hash)
	return b64md5, filepath.Join(c.root, "obj", "md5", hexHash[:2], hexHash[2:])
}

func (c *FileCache) md5Path(b64md5 string) (string, error) {
	hexHash, err := utils.B64ToHex(b64md5)
	if err != nil {
		return "", err
	}
	return filepath.Join(c.root, "obj", "md5", hexHash[:2], hexHash[2:]), nil
}

// If the file with the matching hash is in the cache, return the path to the file.
func (c *FileCache) pathTo(b64md5 string) *string {
	cachePath, err := c.md5Path(b64md5)
	if err != nil {
		return nil
	}
	exists, err := utils.FileExists(cachePath)
	if err != nil {
		return nil
	}
	if exists {
		return &cachePath
	}
	return nil
}

// Check that the file at a path has the same digest as the given digest.
// If not, delete the file.
// Returns true if the file exists and is valid.
func DeleteInvalid(path string, digest string) (bool, error) {
	stat, err := os.Stat(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return false, nil
		}
		return false, err
	}
	if stat.IsDir() {
		os.RemoveAll(path)
		return false, nil
	}
	actualDigest, err := utils.ComputeFileB64MD5(path)
	if err != nil {
		return false, err
	}
	if actualDigest != digest {
		err = os.Remove(path)
		return false, err
	}
	return true, nil
}

// Copy the contents of the reader to the cache and return the B64MD5 cache key.
func (c *FileCache) Write(src io.Reader) (string, error) {
	tmpDir := filepath.Join(c.root, "tmp")
	if err := os.MkdirAll(tmpDir, 0755); err != nil {
		return "", err
	}
	tmpFile, err := os.CreateTemp(tmpDir, "")
	if err != nil {
		return "", err
	}
	defer os.Remove(tmpFile.Name())
	defer tmpFile.Close()

	hasher := md5.New()
	w := io.MultiWriter(tmpFile, hasher)
	_, err = io.Copy(w, src)
	if err != nil {
		return "", err
	}
	b64md5, dstPath := c.keyAndPath(hasher.Sum(nil))
	if exists, _ := utils.FileExists(dstPath); exists {
		return b64md5, nil
	}
	if err := os.MkdirAll(filepath.Dir(dstPath), 0755); err != nil {
		return "", err
	}
	if err := atomicfile.ReplaceFile(tmpFile.Name(), dstPath); err != nil {
		return "", err
	}
	return b64md5, nil
}
