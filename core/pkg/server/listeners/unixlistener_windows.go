//go:build windows

package listeners

import (
	"fmt"
	"net"
	"os"
)

// makeUnixListener starts listening on a Unix domain socket.
func makeUnixListener(parentPID int, portInfo *PortInfo) (net.Listener, error) {
	namePattern := fmt.Sprintf("wandb-%d-%d-*", parentPID, os.Getpid())
	return listenInTempDir(namePattern, portInfo)
}
