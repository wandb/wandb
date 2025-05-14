package tensorboard

import (
	"errors"
	"fmt"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/paths"
)

// RootDirGuesser guesses the roots of TensorBoard tfevents directories.
//
// The Python side of this integration creates TBRecords when
// TensorBoard starts to write to a new directory. TensorBoard internally
// creates this directory by joining a namespace like "train" or
// "validation" to a root path, and we would like to use the namespace
// as a prefix for logged metrics, like "train/epoch_loss" vs
// "validation/epoch_loss".
//
// The namespace itself may include slashes, so we cannot break apart
// a log directory into a (root, namespace) pair until we are tracking
// at least two directories.
type RootDirGuesser struct {
	mu sync.Mutex

	logger *observability.CoreLogger

	localLogDirs *loggingDirectories
	cloudLogDirs map[string]*loggingDirectories
}

func NewRootDirGuesser(logger *observability.CoreLogger) *RootDirGuesser {
	return &RootDirGuesser{
		logger:       logger,
		localLogDirs: newLoggingDirectories(),
		cloudLogDirs: make(map[string]*loggingDirectories),
	}
}

// RootDir is a prefix to remove from tfevents file paths.
type RootDir struct {
	prefixSlashPath string
}

func (d *RootDir) String() string {
	if d == nil {
		return "nil"
	} else {
		return d.prefixSlashPath
	}
}

// NewRootDir creates a RootDir from an explicitly given prefix.
//
// Any backslashes are replaced by forward slashes.
func NewRootDir(prefix string) *RootDir {
	return &RootDir{filepath.ToSlash(prefix)}
}

// RootDirFromCWD creates a RootDir from the current working directory.
func RootDirFromCWD() (*RootDir, error) {
	maybeCWD, err := paths.CWD()
	if err != nil {
		return nil, err
	}
	cwd := *maybeCWD

	return &RootDir{filepath.ToSlash(string(cwd))}, nil
}

// TrimFrom trims the root directory from the path and returns the result.
//
// The result uses forward slashes instead of filepath.Separator.
// If the path isn't under the root, an error is returned.
//
// Returns an error for a nil RootDir.
func (d *RootDir) TrimFrom(path *LocalOrCloudPath) (string, error) {
	if d == nil {
		return "", errors.New("no root directory")
	}

	slashPath := path.ToSlashPath()
	withoutPrefix := strings.TrimPrefix(slashPath, d.prefixSlashPath)

	if d.prefixSlashPath != "" && len(withoutPrefix) == len(slashPath) {
		return "", fmt.Errorf(
			"%q does not start with %q",
			slashPath, d.prefixSlashPath)
	}

	return strings.TrimLeft(withoutPrefix, "/"), nil
}

// InferRootOrTimeout returns the root directory for the given tfevents folder
// after it can be inferred.
//
// After a timeout, it logs a warning and returns nil.
func (g *RootDirGuesser) InferRootOrTimeout(
	path *LocalOrCloudPath,
	timeout time.Duration,
) *RootDir {
	dirs := g.loggingDirectoriesFor(path)
	rootDir, err := dirs.InferRootOrTimeout(timeout)

	if err != nil {
		g.logger.Warn("tensorboard: no root directory", "error", err)
	}

	return rootDir
}

// AddLogDirectory registers a directory containing tfevents files and
// updates the inferred root.
//
// The pathURL may be either a local filesystem path or a cloud path.
func (g *RootDirGuesser) AddLogDirectory(path *LocalOrCloudPath) {
	g.loggingDirectoriesFor(path).Add(path.ToSlashPath())
}

func (g *RootDirGuesser) loggingDirectoriesFor(
	path *LocalOrCloudPath,
) *loggingDirectories {
	g.mu.Lock()
	defer g.mu.Unlock()

	switch {
	case path.LocalPath != nil:
		return g.localLogDirs

	case path.CloudPath != nil:
		dirs := g.cloudLogDirs[path.CloudPath.Scheme]

		if dirs == nil {
			dirs = newLoggingDirectories()
			g.cloudLogDirs[path.CloudPath.Scheme] = dirs
		}

		return dirs

	default:
		panic("tensorboard: RootDirGuesser: invalid path")
	}
}

// loggingDirectories is a set of related tfevents directories.
type loggingDirectories struct {
	mu sync.Mutex

	// inferred is closed when the prefix has been calculated.
	inferred chan struct{}

	// paths contains slash-separated paths whose shared prefix we want.
	paths []string

	// prefix is the longest common path prefix of the paths.
	//
	// It is empty if there aren't enough paths to infer it yet.
	prefix string
}

func newLoggingDirectories() *loggingDirectories {
	return &loggingDirectories{inferred: make(chan struct{})}
}

// InferRootOrTimeout returns the inferred prefix once it's available.
//
// Returns an error on timeout.
func (dirs *loggingDirectories) InferRootOrTimeout(
	timeout time.Duration,
) (*RootDir, error) {
	// Don't time out if the result is available but the timeout is zero.
	select {
	case <-dirs.inferred:
		dirs.mu.Lock()
		defer dirs.mu.Unlock()
		return &RootDir{dirs.prefix}, nil
	default:
	}

	select {
	case <-dirs.inferred:
		dirs.mu.Lock()
		defer dirs.mu.Unlock()
		return &RootDir{dirs.prefix}, nil
	case <-time.After(timeout):
		return nil, fmt.Errorf("timed out after %s", timeout)
	}
}

// Add adds a slash-separated path to the set.
func (dirs *loggingDirectories) Add(path string) {
	dirs.mu.Lock()
	defer dirs.mu.Unlock()

	dirs.paths = append(dirs.paths, path)

	if len(dirs.paths) > 1 {
		dirs.prefix = paths.LongestCommonPrefixStr(slices.Values(dirs.paths), "/")
		close(dirs.inferred)
	}
}
