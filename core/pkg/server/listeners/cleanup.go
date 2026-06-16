package listeners

import (
	"log/slog"
	"os"
	"path/filepath"
	"regexp"
)

var unixSocketDirNamePattern = regexp.MustCompile(`^wandb-\d+-\d+-`)

// CleanupUnixSocketDir removes the temporary directory that holds a Unix domain
// socket created by makeUnixListener.
//
// The unixPath argument is the full path to the socket file (for example
// "/tmp/wandb-1-2-abc/socket"). If unixPath is empty or does not look like a
// path we created, this is a no-op.
func CleanupUnixSocketDir(unixPath string) {
	cleanupUnixSocketDir(unixPath, slog.Default())
}

func cleanupUnixSocketDir(unixPath string, logger *slog.Logger) {
	if unixPath == "" {
		return
	}

	sockDir := filepath.Dir(unixPath)
	if !isWandbUnixSocketDir(sockDir) {
		logger.Warn(
			"server/listeners: refusing to remove unexpected Unix socket directory",
			"dir", sockDir,
		)
		return
	}

	if err := os.RemoveAll(sockDir); err != nil {
		logger.Warn(
			"server/listeners: failed to remove Unix socket directory",
			"dir", sockDir,
			"error", err,
		)
	}
}

func isWandbUnixSocketDir(dir string) bool {
	dir = filepath.Clean(dir)
	if !unixSocketDirNamePattern.MatchString(filepath.Base(dir)) {
		return false
	}

	parent := filepath.Dir(dir)
	if parent == filepath.Clean(os.TempDir()) {
		return true
	}

	return parent == filepath.Clean("/tmp")
}
