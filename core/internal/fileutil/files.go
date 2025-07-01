package fileutil

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"unicode"
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
	defer func() {
		_ = source.Close()
	}()

	// Create destination directory if it doesn't exist
	if err := os.MkdirAll(filepath.Dir(dst), 0755); err != nil {
		return fmt.Errorf("unable to create destination directory %s: %w", filepath.Dir(dst), err)
	}

	destination, err := os.Create(dst)
	if err != nil {
		return fmt.Errorf("unable to create destination file %s: %w", dst, err)
	}
	defer func() {
		_ = destination.Close()
	}()

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
	defer func() {
		_ = destination.Close()
	}()

	// Copy the contents of the reader to the destination file
	if _, err := io.Copy(destination, reader); err != nil {
		return fmt.Errorf("copy failed: %w", err)
	}

	return nil
}

// SanitizeWindowsFilename removes or replaces invalid characters from a
// filename for Windows.
func SanitizeWindowsFilename(filename string) string {
	// Forbidden characters
	forbiddenChars := []rune{'<', '>', ':', '"', '/', '\\', '|', '?', '*'}

	// Replace forbidden characters with an underscore
	for _, char := range forbiddenChars {
		filename = strings.ReplaceAll(filename, string(char), "_")
	}

	// Trim trailing spaces and dots
	filename = strings.TrimRightFunc(filename, func(r rune) bool {
		return r == ' ' || r == '.'
	})

	// Reserved names (case-insensitive)
	reservedNames := map[string]bool{
		"CON": true, "PRN": true, "AUX": true, "NUL": true,
		"COM1": true, "COM2": true, "COM3": true, "COM4": true,
		"COM5": true, "COM6": true, "COM7": true, "COM8": true, "COM9": true,
		"LPT1": true, "LPT2": true, "LPT3": true, "LPT4": true, "LPT5": true,
		"LPT6": true, "LPT7": true, "LPT8": true, "LPT9": true,
	}

	upperFilename := strings.ToUpper(filename)
	if reservedNames[upperFilename] {
		filename += "_safe" // Add a suffix to reserved names
	}

	return filename
}

// SanitizeLinuxFilename removes or replaces problematic characters for Linux
// filenames.
func SanitizeLinuxFilename(filename string) string {
	var sanitized strings.Builder
	for _, r := range filename {
		switch {
		case r == '/', r == '\x00': // Forbidden characters
			sanitized.WriteRune('_')
		case unicode.IsControl(r): // Control characters
			continue
		default:
			sanitized.WriteRune(r)
		}
	}

	// Trim leading/trailing spaces and dots
	return strings.TrimSpace(strings.TrimRight(sanitized.String(), "."))
}

// SanitizeFilename removes or replaces problematic characters from a filename
// for the current operating system.
func SanitizeFilename(filename string) string {
	if runtime.GOOS == "windows" {
		return SanitizeWindowsFilename(filename)
	}
	return SanitizeLinuxFilename(filename)
}
