package utils

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

func FileExists(path string) (bool, error) {
	_, err := os.Stat(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

// CopyFile copies the contents of `src` into `dst`.
//
// If the source doesn't exist this is a no-op and an error is returned.
//
// If the destination exists, it will be overwritten.
//
// This operation is not atomic: if either the source or destination files are modified
// during the copy, the destination file's contents may be corrupted.
func CopyFile(src, dst string) error {
	source, err := os.Open(src)
	if err != nil {
		return fmt.Errorf("failed to open source file: %v", err)
	}
	defer source.Close()

	if err := os.MkdirAll(filepath.Dir(dst), 0755); err != nil {
		return fmt.Errorf("failed to create destination folder: %v", err)
	}
	destination, err := os.Create(dst)
	if err != nil {
		return fmt.Errorf("failed to create destination file: %v", err)
	}
	defer destination.Close()

	_, err = io.Copy(destination, source)
	if err != nil {
		return err
	}
	return nil
}

func WriteJsonToFileWithDigest(data any) (filename string, digest string, size int64, rerr error) {
	dataJSON, rerr := json.Marshal(data)
	if rerr != nil {
		return
	}

	f, rerr := os.CreateTemp("", "tmpfile-")
	if rerr != nil {
		return
	}
	defer f.Close()
	_, rerr = f.Write(dataJSON)
	if rerr != nil {
		return
	}
	filename = f.Name()

	if stat, err := f.Stat(); err == nil { // if NO error
		size = stat.Size()
	}

	digest = ComputeB64MD5(dataJSON)
	return
}
