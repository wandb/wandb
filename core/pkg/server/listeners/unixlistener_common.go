package listeners

import (
	"fmt"
	"net"
	"os"
	"path/filepath"
)

// listenInTempDir attempts to listen on a path constructed from os.TempDir().
//
// This is preferred over /tmp on macOS, but it may not work if the temporary
// directory is very long because Unix sockets are generally limited to 92-108
// characters.
func listenInTempDir(
	namePattern string,
	portInfo *PortInfo,
) (net.Listener, error) {
	sockDir, err := makeUniqueDir(os.TempDir(), namePattern)

	if err != nil {
		return nil, fmt.Errorf(
			"server/listeners: failed to make tempdir for Unix socket: %v", err)
	}

	return listenUnix(filepath.Join(sockDir, "socket"), portInfo)
}

// makeUniqueDir creates a unique directory as os.MkdirTemp().
//
// This is necessary to avoid conflicts with other processes. We couldn't just
// use "/tmp/wandb-<pid>" as the socket name, for instance, because another
// process (maybe another W&B product) could rely on a "/tmp/wandb-<number>"
// file.
//
// The directory's default permissions (0o700) mean the socket will be
// accessible only by programs running as the same user. wandb-core runs as
// the user of the Python process that started it.
func makeUniqueDir(dir string, namePattern string) (string, error) {
	return os.MkdirTemp(dir, namePattern)
}

// listenUnix attempts to listen on a Unix socket with the given path.
func listenUnix(path string, portInfo *PortInfo) (net.Listener, error) {
	listener, err := net.Listen("unix", path)

	if err != nil {
		return nil, fmt.Errorf(
			"server/listeners: failed to open Unix socket on %q: %v",
			path, err)
	}

	portInfo.UnixPath = path
	return listener, nil
}
