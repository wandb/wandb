// Package listeners opens listening sockets for IPC.
package listeners

import (
	"errors"
	"log/slog"
	"net"
)

// Config contains the parameters for MakeListeners().
type Config struct {
	// ParentPID is the PID of our parent process, used for naming Unix sockets.
	ParentPID int

	// ListenOnLocalhost ensures that we open a localhost socket
	// in addition to any other IPC mechanisms that work.
	//
	// These sockets are less secure than Unix sockets: Unix sockets use
	// the file permission system, so that only processes running as the same
	// user can connect to the socket, but anyone can connect to a localhost
	// socket.
	//
	// Unfortunately, not all clients support Unix sockets.
	ListenOnLocalhost bool
}

// MakeListeners creates listeners for interprocess communication.
func (c Config) MakeListeners() ([]net.Listener, PortInfo, error) {
	var listeners []net.Listener
	var portInfo PortInfo
	var errs []error

	unixListener, err := makeUnixListener(c.ParentPID, &portInfo)
	if err != nil {
		errs = append(errs, err)
	} else {
		listeners = append(listeners, unixListener)
	}

	if c.ListenOnLocalhost || unixListener == nil {
		tcpListener, err := makeTCPListener(&portInfo)

		if err != nil {
			errs = append(errs, err)
		} else {
			listeners = append(listeners, tcpListener)
		}
	}

	if len(listeners) == 0 {
		return nil, portInfo, errors.Join(errs...)
	}

	if len(errs) > 0 {
		slog.Warn(
			"server/listeners: failed to make some listeners",
			"error", errors.Join(errs...),
		)
	}

	return listeners, portInfo, nil
}
