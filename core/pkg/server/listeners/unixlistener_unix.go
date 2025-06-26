//go:build unix

package listeners

import (
	"fmt"
	"log/slog"
	"net"
	"os"
	"path/filepath"
)

// makeUnixListener starts listening on a Unix domain socket.
//
// This tries os.TempDir() and /tmp on Unix-like systems. We don't try
// /var/run because it usually requires root permissions.
func makeUnixListener(parentPID int, portInfo *PortInfo) (net.Listener, error) {
	namePattern := fmt.Sprintf("wandb-%d-%d-*", parentPID, os.Getpid())

	listener, err := listenInTempDir(namePattern, portInfo)
	if err == nil {
		return listener, nil
	}
	slog.Warn(
		"server/listeners: couldn't open Unix socket in os.TempDir()",
		"error", err,
	)

	return listenInTmp(namePattern, portInfo)
}

// listenInTmp attemps to listen on a path under /tmp.
//
// On macOS, os.TempDir() points to a per-user temporary folder under
// /var/folders (with more secure permissions than /tmp) but the path may be too
// long.
func listenInTmp(namePattern string, portInfo *PortInfo) (net.Listener, error) {
	sockDir, err := makeUniqueDir("/tmp", namePattern)

	if err != nil {
		return nil, fmt.Errorf(
			"server/listeners: failed to make folder in /tmp for Unix socket: %v",
			err,
		)
	}

	return listenUnix(filepath.Join(sockDir, "socket"), portInfo)
}
