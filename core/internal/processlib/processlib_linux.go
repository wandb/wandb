package processlib

import (
	"os"
	"syscall"
)

const (
	PRCTL_SYSCALL    = 157
	PR_SET_PDEATHSIG = 1
)

func ShutdownOnParentExit(parentPid int) bool {
	_, _, errno := syscall.Syscall(
		uintptr(PRCTL_SYSCALL), uintptr(PR_SET_PDEATHSIG), uintptr(syscall.SIGKILL), 0)
	if errno != 0 {
		os.Exit(127 + int(errno))
	}
	// Check again because the process could have exited right before the syscall was made
	if os.Getppid() != parentPid {
		os.Exit(1)
	}
	return true
}
