package artifacts

import (
	"bytes"
	"crypto/md5"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"hash"
	"io"
	"os"
	"path/filepath"
	"time"

	atomicfile "github.com/natefinch/atomic"
	"github.com/wandb/wandb/core/pkg/utils"
)

type FileCache struct {
	root string
}

func NewFileCache() *FileCache {
	dir := os.Getenv("WANDB_CACHE_DIR")
	if dir == "" {
		dir, _ = os.UserCacheDir()
		dir = filepath.Join(dir, "wandb")
	}
	return &FileCache{root: filepath.Join(dir, "artifacts")}
}

func (c *FileCache) md5Path(b64md5 string) (string, error) {
	hexHash, err := utils.B64ToHex(b64md5)
	if err != nil {
		return "", err
	}
	return filepath.Join(c.root, "obj", "md5", hexHash[:2], hexHash[2:]), nil
}

func (c *FileCache) FindMd5(b64md5 string) (*cacheFile, error) {
	path, err := c.md5Path(b64md5)
	if err != nil {
		return nil, err
	}
	return getCacheFile(path)
}

func (c *FileCache) etagPath(etag, url string) (string, error) {
	urlHash := sha256.Sum256([]byte(url))
	etagHash := sha256.Sum256([]byte(etag))
	concatHash := sha256.Sum256(append(urlHash[:], etagHash[:]...))
	hexHash := hex.EncodeToString(concatHash[:])

	return filepath.Join(c.root, "obj", "etag", hexHash[:2], hexHash[2:]), nil
}

func (c *FileCache) FindEtag(etag string, url string) *cacheFile {
	path, _ := c.etagPath(etag, url)
	targetFile, _ := getCacheFile(path)
	return targetFile
}

// Write a blob into the cache and return the B64MD5 hash key.
func (c *FileCache) Write(data []byte) (string, error) {
	hasher := md5.New()
	if _, err := hasher.Write(data); err != nil {
		return "", err
	}
	b64md5 := base64.StdEncoding.EncodeToString(hasher.Sum(nil))
	hexHash := hex.EncodeToString(hasher.Sum(nil))
	path := filepath.Join(c.root, "obj", "md5", hexHash[:2], hexHash[2:])
	if exists, _ := utils.FileExists(path); exists {
		return b64md5, nil
	}
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return "", err
	}
	if err := atomicfile.WriteFile(path, bytes.NewReader(data)); err != nil {
		return "", err
	}
	return b64md5, nil
}

// Copy a file into the cache and return the B64MD5 hash key.
func (c *FileCache) CopyFrom(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()

	tmpDir := filepath.Join(c.root, "tmp")
	if err := os.MkdirAll(tmpDir, 0755); err != nil {
		return "", err
	}
	tmpPath, err := os.CreateTemp(tmpDir, "")
	if err != nil {
		return "", err
	}
	defer os.Remove(tmpPath.Name())
	defer tmpPath.Close()

	hasher := md5.New()
	w := io.MultiWriter(tmpPath, hasher)
	_, err = io.Copy(w, f)
	if err != nil {
		return "", err
	}
	b64md5 := base64.StdEncoding.EncodeToString(hasher.Sum(nil))
	hexHash := hex.EncodeToString(hasher.Sum(nil))
	dstPath := filepath.Join(c.root, "obj", "md5", hexHash[:2], hexHash[2:])
	if exists, _ := utils.FileExists(dstPath); exists {
		return b64md5, nil
	}
	if err := os.MkdirAll(filepath.Dir(dstPath), 0755); err != nil {
		return "", err
	}
	if err := atomicfile.ReplaceFile(tmpPath.Name(), dstPath); err != nil {
		return "", err
	}
	return b64md5, nil
}

// Identify an etag with the blob that has the given hash.
func (c *FileCache) LinkEtag(etag, url, b64md5 string) error {
	hashPath, err := c.md5Path(b64md5)
	if err != nil {
		return err
	}
	exists, err := utils.FileExists(hashPath)
	if err != nil {
		return err
	}
	if !exists {
		return fmt.Errorf("no cache file with hash %s", b64md5)
	}
	etagPath, err := c.etagPath(etag, url)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(etagPath), 0755); err != nil {
		return err
	}
	return os.Symlink(hashPath, etagPath)
}

// Try to restore the file referenced in a manifest entry to the given destination.
//
// Returns true if the file was restored successfully.
//
// If the file is already at the destination, this function is a no-op and returns true.
// If the file is in the cache, it will be copied to the destination.
// If the file is neither in the cache nor at the destination, or if we encounter any
// error, then this function return false.
//
// Note that this function does not verify the integrity of the restored file.
func (c *FileCache) RestoreTo(entry ManifestEntry, dst string) bool {
	if exists, _ := utils.FileExists(dst); exists {
		return true
	}
	var cacheCopy *cacheFile
	if entry.Ref != nil {
		cacheCopy = c.FindEtag(entry.Digest, *entry.Ref)
	} else {
		cacheCopy, _ = c.FindMd5(entry.Digest)
	}
	if cacheCopy == nil {
		return false
	}
	// TODO (hugh): should we set the LocalPath in the entry to the dst?
	return cacheCopy.CopyTo(dst) == nil
}

func (c *FileCache) newCacheWriter() *cacheWriter {
	tmpDir := filepath.Join(c.root, "tmp")
	if err := os.MkdirAll(tmpDir, 0755); err != nil {
		return nil
	}
	tmpFile, err := os.CreateTemp(tmpDir, "")
	if err != nil {
		return nil
	}
	hasher := md5.New()
	w := io.MultiWriter(tmpFile, hasher)
	return &cacheWriter{cache: c, writer: w, tmpFile: tmpFile, hasher: hasher}
}

type cacheFile struct {
	path    string
	size    int64
	modTime time.Time
}

func getCacheFile(path string) (*cacheFile, error) {
	stat, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("unable to stat file: %w", err)
	}
	size := stat.Size()
	if stat.Mode()&os.ModeSymlink != 0 {
		// If a symbolic link is broken delete it and move on. Otherwise resolve it.
		realPath, err := os.Readlink(path)
		if err != nil {
			os.Remove(path)
			return nil, nil
		}
		realStat, err := os.Stat(realPath)
		if err != nil {
			os.Remove(path)
			return nil, nil
		}
		path = realPath
		size = realStat.Size()
	}
	return &cacheFile{path: path, size: size, modTime: stat.ModTime()}, nil
}

func (f *cacheFile) CopyTo(dst string) error {
	exists, err := utils.FileExists(dst)
	if err != nil {
		return err
	}
	if exists {
		stat, err := os.Stat(dst)
		if err != nil {
			return err
		}
		if stat.Size() == f.size {
			return nil
		}
		// Should we return an error if there's a size mismatch? Here we just overwrite.
	}
	return utils.CopyFile(f.path, dst)
}

// Open returns a writer that writes to the cache.
type cacheWriter struct {
	cache   *FileCache
	writer  io.Writer
	tmpFile *os.File
	hasher  hash.Hash
	b64md5  *string
}

func (c *cacheWriter) Write(p []byte) (int, error) {
	return c.writer.Write(p)
}

func (c *cacheWriter) close() (string, error) {
	if c.tmpFile == nil {
		return "", fmt.Errorf("already closed")
	}
	if err := c.tmpFile.Close(); err != nil {
		return "", err
	}
	h := c.hasher.Sum(nil)
	b64md5 := base64.StdEncoding.EncodeToString(h)
	hexHash := hex.EncodeToString(h)
	dstPath := filepath.Join(c.cache.root, "obj", "md5", hexHash[:2], hexHash[2:])
	if err := os.MkdirAll(filepath.Dir(dstPath), 0755); err != nil {
		return "", err
	}
	if err := atomicfile.ReplaceFile(c.tmpFile.Name(), dstPath); err != nil {
		os.Remove(c.tmpFile.Name())
		c.tmpFile = nil
		return "", err
	}
	c.tmpFile = nil
	c.b64md5 = &b64md5
	return b64md5, nil
}

// Get the B64MD5 hash of file just written. First close the writer if necessary.
// Calling c.Write() after calling c.B64Md5() will result in an error.
func (c *cacheWriter) B64Md5() string {
	if c.b64md5 == nil {
		b64md5, err := c.close()
		if err != nil {
			return ""
		}
		c.b64md5 = &b64md5
	}
	return *c.b64md5
}
