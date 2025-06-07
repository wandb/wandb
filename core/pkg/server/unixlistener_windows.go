//go:build windows

package server

import (
	"fmt"
	"net"
	"os"
)

// MakeUnixListener starts listening on a Unix domain socket.
func MakeUnixListener(parentPID int) (net.Listener, PortInfo, error) {
	namePattern := fmt.Sprintf("wandb-%d-%d-*", parentPID, os.Getpid())
	return listenInTempDir(namePattern)
}
