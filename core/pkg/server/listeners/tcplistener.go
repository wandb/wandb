package listeners

import (
	"fmt"
	"net"
)

// makeTCPListener starts listening on a localhost socket.
func makeTCPListener(portInfo *PortInfo) (net.Listener, error) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return nil, fmt.Errorf(
			"server/listeners: failed to listen on localhost: %v", err)
	}

	portInfo.LocalhostPort = listener.Addr().(*net.TCPAddr).Port
	return listener, nil
}
