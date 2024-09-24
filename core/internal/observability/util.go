package observability

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"time"
)

// this is for storing the commit hash in context.Context
type commitType string

const Commit = commitType("commit")

// FileSystem interface to abstract file system operations
type FileSystem interface {
	MkdirAll(path string, perm os.FileMode) error
	OpenFile(name string, flag int, perm os.FileMode) (fs.File, error)
}

// OsFs wraps standard os package functions to satisfy the FileSystem interface.
type OsFs struct{}

func (OsFs) MkdirAll(path string, perm os.FileMode) error {
	return os.MkdirAll(path, perm)
}

func (OsFs) OpenFile(name string, flag int, perm os.FileMode) (fs.File, error) {
	return os.OpenFile(name, flag, perm)
}

func GetLoggerPath() (*os.File, error) {
	osFs := OsFs{}
	file, err := GetLoggerPathFS(osFs)

	if err != nil {
		return nil, err
	}

	osfile, ok := file.(*os.File)
	if !ok {
		return nil, fmt.Errorf("file is not an *os.File")
	}

	return osfile, nil
}

// GetLoggerPathFS function with FileSystem parameter
func GetLoggerPathFS(fs FileSystem) (fs.File, error) {
	// TODO: replace with a setting during client rewrite
	dir := os.Getenv("WANDB_CACHE_DIR")
	if dir == "" {
		dir, _ = os.UserCacheDir()
	}

	if dir == "" {
		return nil, fmt.Errorf("failed to get logger path")
	}

	dir, err := filepath.Abs(dir)
	if err != nil {
		return nil, fmt.Errorf("failed to get logger path: %s", err)
	}

	timestamp := time.Now().Format("20060102_150405")
	path := filepath.Join(dir, "wandb", "logs", fmt.Sprintf("core-debug-%s.log", timestamp))

	if err := fs.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return nil, fmt.Errorf("error creating log directory: %s", err)
	}

	file, err := fs.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0666)
	if err != nil {
		return nil, fmt.Errorf("error opening log file: %s", err)
	}

	return file, nil
}
