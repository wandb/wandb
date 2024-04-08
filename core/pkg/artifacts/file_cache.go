package artifacts

import (
	"bytes"
	"crypto/md5"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"hash"
	"io"
	"os"
	"path/filepath"
	"syscall"

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

type CacheFile struct {
	path string
}

func (f *CacheFile) CopyTo(path string) error {
	return utils.CopyFile(f.path, path)
}

func (c *FileCache) md5Path(b64md5 string) (string, error) {
	hexHash, err := utils.B64ToHex(b64md5)
	if err != nil {
		return "", err
	}
	return filepath.Join(c.root, "obj", "md5", hexHash[:2], hexHash[2:]), nil
}

func (c *FileCache) FindMd5(b64md5 string) *CacheFile {
	path, err := c.md5Path(b64md5)
	if err != nil {
		return nil
	}
	if exists, _ := utils.FileExists(path); exists {
		return &CacheFile{path: path}
	}
	return nil
}

func (c *FileCache) etagPath(etag, url string) (string, error) {
	urlHash := sha256.Sum256([]byte(url))
	etagHash := sha256.Sum256([]byte(etag))
	concatHash := sha256.Sum256(append(urlHash[:], etagHash[:]...))
	hexHash := hex.EncodeToString(concatHash[:])

	return filepath.Join(c.root, "obj", "etag", hexHash[:2], hexHash[2:]), nil
}

func (c *FileCache) FindEtag(etag string, url string) *CacheFile {
	path, _ := c.etagPath(etag, url)
	if exists, _ := utils.FileExists(path); exists {
		return &CacheFile{path: path}
	}
	return nil
}

// Write a blob into the cache and return the B64MD5 hash key.
func (c *FileCache) Write(data []byte) (string, error) {
	hasher := md5.New()
	if _, err := hasher.Write(data); err != nil {
		return "", err
	}
	b64md5 := hex.EncodeToString(hasher.Sum(nil))
	hexHash := hex.EncodeToString(hasher.Sum(nil))
	path := filepath.Join(c.root, "obj", "md5", hexHash[:2], hexHash[2:])
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

	tmpPath, err := os.CreateTemp(filepath.Join(c.root, "tmp"), "")
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
	b64md5 := hex.EncodeToString(hasher.Sum(nil))
	hexHash := hex.EncodeToString(hasher.Sum(nil))
	dstPath := filepath.Join(c.root, "obj", "md5", hexHash[:2], hexHash[2:])
	if err := atomicfile.ReplaceFile(tmpPath.Name(), dstPath); err != nil {
		return "", err
	}
	return b64md5, nil
}

// Open returns a writer that writes to the cache.
type cacheWriter struct {
	cache   *FileCache
	writer  io.Writer
	tmpFile *os.File
	hasher  hash.Hash
	b64md5  *string
}

func (c *FileCache) newCacheWriter() *cacheWriter {
	tmpFile, err := os.CreateTemp(filepath.Join(c.root, "tmp"), "")
	if err != nil {
		return nil
	}
	hasher := md5.New()
	w := io.MultiWriter(tmpFile, hasher)
	return &cacheWriter{cache: c, writer: w, tmpFile: tmpFile, hasher: hasher}
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
	b64md5 := hex.EncodeToString(h)
	hexHash := hex.EncodeToString(h)
	dstPath := filepath.Join(c.cache.root, "obj", "md5", hexHash[:2], hexHash[2:])
	if err := atomicfile.ReplaceFile(c.tmpFile.Name(), dstPath); err != nil {
		os.Remove(c.tmpFile.Name())
		c.tmpFile = nil
		return "", err
	}
	c.tmpFile = nil
	c.b64md5 = &b64md5
	return b64md5, nil
}

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
	return os.Symlink(hashPath, etagPath)
}

func (c *FileCache) freeSpace() (int64, error) {
	var stat syscall.Statfs_t
	if err := syscall.Statfs(c.root, &stat); err != nil {
		return 0, err
	}
	return int64(stat.Bfree) * int64(stat.Bsize), nil
}
