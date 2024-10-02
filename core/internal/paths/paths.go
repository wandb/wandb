// Package paths enables a "parse-don't-validate" approach to file paths.
//
// Defines `AbsolutePath` and `RelativePath` types. These should be passed by
// value when they're guaranteed to be present, and otherwise by pointer so
// that a nil value can represent an unset path.
//
// The text representation can be retrieved as `string(path)`. For pointers to
// paths, you can use `string(*path)` if a panic is impossible, or
// `path.OrEmpty()` otherwise.
//
// Instead of checking that arbitrary strings are valid inputs, this helps use
// the type system to ensure that they were validated somewhere earlier in the
// call stack. The `AbsolutePath` and `RelativePath` types make for better
// function signatures and specify clear guarantees.
package paths

import (
	"fmt"
	"os"
	"path/filepath"
)

// AbsolutePath is a cleaned, absolute path using the OS file separator.
//
// It does not end with a trailing slash except if it is a root directory,
// such as '/' on Unix or 'C:\' on Windows.
type AbsolutePath string

// RelativePath is a cleaned, relative path using the OS file separator.
//
// The path is guaranteed non-empty. It may start with zero or more ".."
// components, but it does not contain ".." in the middle or at the end.
// It may just be ".".
//
// It does not end with a trailing slash.
type RelativePath string

// OrEmpty returns the path, or an empty string if the path is nil.
func (path *AbsolutePath) OrEmpty() string {
	if path == nil {
		return ""
	} else {
		return string(*path)
	}
}

// OrEmpty returns the path, or an empty string if the path is nil.
func (path *RelativePath) OrEmpty() string {
	if path == nil {
		return ""
	} else {
		return string(*path)
	}
}

// CWD returns the current working directory.
//
// It may fail if the directory has been deleted.
func CWD() (*AbsolutePath, error) {
	cwd, err := os.Getwd()
	if err != nil {
		return nil, err
	}

	// Getwd() always returns an absolute path.
	return toPtr(AbsolutePath(filepath.Clean(cwd))), nil
}

// Absolute makes a path absolute.
//
// If the path is already absolute, this returns a cleaned absolute path.
// If it's relative, it's made absolute by joining to the current working
// directory. An empty string becomes the current working directory.
//
// This may return an error if it fails to get the working directory,
// which can happen if it was deleted.
func Absolute(path string) (*AbsolutePath, error) {
	absPath, err := filepath.Abs(path)
	if err != nil {
		return nil, err
	}

	// NOTE: filepath.Abs() calls Clean() on the result.
	return toPtr(AbsolutePath(absPath)), nil
}

// Relative returns the path if it's relative, or returns an error.
func Relative(path string) (*RelativePath, error) {
	if filepath.IsAbs(path) {
		return nil, fmt.Errorf("path is not relative: %s", path)
	}

	return toPtr(RelativePath(filepath.Clean(path))), nil
}

// RelativeTo returns an equivalent path that is relative to the given path.
//
// On Unix, this will always succeed. On Windows, this may fail if the paths
// are on different volumes, such as "C:\file1" and "D:\file2", in which case
// there is no way to represent them relative to each other.
func (path1 AbsolutePath) RelativeTo(path2 AbsolutePath) (*RelativePath, error) {
	result, err := filepath.Rel(string(path2), string(path1))

	if err != nil {
		return nil, err
	}

	// The result is guaranteed non-empty: if path1 and path2 are equivalent,
	// filepath returns ".".
	//
	// NOTE: filepath.Rel() calls Clean() on the result.
	return toPtr(RelativePath(result)), nil
}

// IsLocal reports whether the relative path does not start with "..".
func (path RelativePath) IsLocal() bool {
	return filepath.IsLocal(string(path))
}

// Something that should exist in Go's standard library.
func toPtr[T any](x T) *T {
	return &x
}
