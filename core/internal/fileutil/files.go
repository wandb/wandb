package fileutil

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

// FileExists checks if a file exists at the given path.
//
// Returns true if the file exists, false if it doesn't, and an error if the file's
// existence cannot be determined.
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

// CopyFile copies a file from the source path to the destination path.
//
// If the destination directory does not exist, it will be created.
// If the destination file already exists, it will be overwritten.
// Permissions of the source file are preserved.
// Returns an error if something goes wrong during the process.
//
// Note: This function is not suitable for copying large files, as it reads the entire
// file into memory before writing it to the destination.
func CopyFile(src, dst string) error {
	source, err := os.Open(src)
	if err != nil {
		return fmt.Errorf("unable to open source file %s: %w", src, err)
	}
	defer source.Close()

	// Create destination directory if it doesn't exist
	if err := os.MkdirAll(filepath.Dir(dst), 0755); err != nil {
		return fmt.Errorf("unable to create destination directory %s: %w", filepath.Dir(dst), err)
	}

	destination, err := os.Create(dst)
	if err != nil {
		return fmt.Errorf("unable to create destination file %s: %w", dst, err)
	}
	defer destination.Close()

	// Copy the contents of the source file to the destination file
	if _, err := io.Copy(destination, source); err != nil {
		return fmt.Errorf("copy failed: %w", err)
	}

	// Preserve file permissions from the source file
	if info, err := os.Stat(src); err == nil {
		if err := os.Chmod(dst, info.Mode()); err != nil {
			return fmt.Errorf("failed to set file permissions on %s: %w", dst, err)
		}
	} else {
		return fmt.Errorf("unable to get source file info %s: %w", src, err)
	}

	return nil
}

// CopyReaderToFile copies the contents of a reader to the destination path.
//
// If the destination directory does not exist, it will be created.
// If the destination file already exists, it will be overwritten.
// Returns an error if something goes wrong during the process.
func CopyReaderToFile(reader io.Reader, dst string) error {
	// Create destination directory if it doesn't exist
	if err := os.MkdirAll(filepath.Dir(dst), 0755); err != nil {
		return fmt.Errorf("unable to create destination directory %s: %w", filepath.Dir(dst), err)
	}

	destination, err := os.Create(dst)
	if err != nil {
		return fmt.Errorf("unable to create destination file %s: %w", dst, err)
	}
	defer destination.Close()

	// Copy the contents of the reader to the destination file
	if _, err := io.Copy(destination, reader); err != nil {
		return fmt.Errorf("copy failed: %w", err)
	}

	return nil
}
