//go:build !linux

package processlib

func ShutdownOnParentDeath(parentPid int) {
}
