package filetransfer

import (
	"errors"
	"path/filepath"
)

// ErrPathTraversal is returned when a path contains traversal sequences
// that would escape the base directory.
var ErrPathTraversal = errors.New("path traversal detected")

// SafeJoinPath safely joins a base path with an untrusted relative path.
// It returns an error if the relative path would escape the base directory
// through path traversal sequences like "../".
//
// This function should be used when constructing local file paths from
// untrusted sources (e.g., cloud storage object keys) to prevent
// arbitrary file writes outside the intended directory.
func SafeJoinPath(basePath, untrustedRelative string) (string, error) {
	// Convert forward slashes to OS-specific separator
	cleaned := filepath.FromSlash(untrustedRelative)

	// IsLocal reports whether path, using lexical analysis only, has all of these properties:
	//
	//   - is within the subtree rooted at the directory in which path is evaluated
	//   - is not an absolute path
	//   - is not empty
	//   - on Windows, is not a reserved name such as "NUL"

	// Special case an empty relative path as it is valid (and means the base path itself),
	// which is acceptable.
	if untrustedRelative != "" && !filepath.IsLocal(cleaned) {
		return "", ErrPathTraversal
	}

	return filepath.Join(basePath, cleaned), nil
}
