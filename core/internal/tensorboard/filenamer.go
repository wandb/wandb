package tensorboard

import (
	"errors"
	"path/filepath"
)

// FileNamer determines the run path where to save a tfevents file.
type FileNamer func(path *LocalOrCloudPath) (string, error)

// PrefixFileNamer puts local files into the run directory specified by
// `prefix`.
//
// Returns an error for paths that aren't local (like S3 paths).
func PrefixFileNamer(prefix string) FileNamer {
	return func(path *LocalOrCloudPath) (string, error) {
		localPath := path.LocalPath.OrEmpty()
		if localPath == "" {
			return "", errors.New("not a local file")
		}

		return filepath.Join(prefix, filepath.Base(localPath)), nil
	}
}

// RootDirFileNamer determines the run path by trimming the "root directory"
// from a tfevents file's actual path.
//
// Can return an error if this fails, like if the given path does not have
// the root directory as a prefix.
func RootDirFileNamer(rootDir *RootDir) FileNamer {
	return func(path *LocalOrCloudPath) (string, error) {
		return rootDir.TrimFrom(path)
	}
}
