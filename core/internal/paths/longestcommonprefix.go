package paths

import (
	"errors"
	"fmt"
	"path/filepath"
	"strings"
)

// LongestCommonPrefix returns the longest path that every given path
// starts with.
func LongestCommonPrefix(paths []AbsolutePath) (*AbsolutePath, error) {
	if len(paths) < 2 {
		return nil, errors.New("too few paths")
	}

	longestPrefix := strings.Split(
		string(paths[0]),
		string(filepath.Separator),
	)

	for _, path := range paths[1:] {
		pathParts := strings.Split(string(path), string(filepath.Separator))

		for i, part := range longestPrefix {
			if part != pathParts[i] {
				longestPrefix = longestPrefix[:i]
				break
			}
		}
	}

	rootDir, err := Absolute(
		strings.Join(longestPrefix, string(filepath.Separator)),
	)
	if err != nil {
		return nil, fmt.Errorf("error making path absolute: %v", err)
	}

	return rootDir, nil
}
