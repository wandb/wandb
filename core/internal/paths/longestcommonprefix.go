package paths

import (
	"errors"
	"fmt"
	"iter"
	"path/filepath"
	"strings"
)

// LongestCommonPrefix returns the longest path that every given path
// starts with.
func LongestCommonPrefix(paths []AbsolutePath) (*AbsolutePath, error) {
	if len(paths) < 2 {
		return nil, errors.New("too few paths")
	}

	pathStrs := func(yield func(string) bool) {
		for _, path := range paths {
			if !yield(string(path)) {
				break
			}
		}
	}

	rootDirStr := LongestCommonPrefixStr(
		pathStrs,
		string(filepath.Separator),
	)

	rootDir, err := Absolute(rootDirStr)
	if err != nil {
		return nil, fmt.Errorf("error making path absolute: %v", err)
	}

	return rootDir, nil
}

// LongestCommonPrefixStr returns the longest sequence of path components that
// every given path starts with.
//
// It accepts a sequence of strings and the separator to use to break strings
// into path components.
func LongestCommonPrefixStr(paths iter.Seq[string], separator string) string {
	var longestPrefix []string

	for path := range paths {
		pathParts := strings.Split(path, separator)

		if longestPrefix == nil {
			longestPrefix = pathParts
			continue
		}

		for i, part := range longestPrefix {
			if part != pathParts[i] {
				longestPrefix = longestPrefix[:i]
				break
			}
		}
	}

	return strings.Join(longestPrefix, string(separator))
}
