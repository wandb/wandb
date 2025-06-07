//go:build unix

package server

import (
	"fmt"
	"log/slog"
	"net"
	"os"
	"path/filepath"
)

// MakeUnixListener starts listening on a Unix domain socket.
//
// This tries os.TempDir() and /tmp on Unix-like systems. We don't try
// /var/run because it usually requires root permissions.
func MakeUnixListener(parentPID int) (net.Listener, PortInfo, error) {
	namePattern := fmt.Sprintf("wandb-%d-%d-*", parentPID, os.Getpid())

	listener, portInfo, err := listenInTempDir(namePattern)
	if err == nil {
		return listener, portInfo, nil
	}
	slog.Warn("server: couldn't open Unix socket in os.TempDir()", "error", err)

	return listenInTmp(namePattern)
}

// listenInTmp attemps to listen on a path under /tmp.
//
// On macOS, os.TempDir() points to a per-user temporary folder under
// /var/folders (with more secure permissions than /tmp) but the path may be too
// long.
func listenInTmp(namePattern string) (net.Listener, PortInfo, error) {
	sockDir, err := makeUniqueDir("/tmp", namePattern)

	if err != nil {
		return nil, PortInfo{}, fmt.Errorf(
			"server: failed to make folder in /tmp for Unix socket: %v", err)
	}

	return listen(filepath.Join(sockDir, "socket"))
}
