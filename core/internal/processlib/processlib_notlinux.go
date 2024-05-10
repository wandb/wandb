//go:build !linux

package processlib

func ShutdownOnParentExit(parentPid int) bool {
	// This is not supported on platforms other than linux
	return false
}
