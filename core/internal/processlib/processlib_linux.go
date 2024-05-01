package processlib

import (
	"os"
	"syscall"
)

const (
	PRCTL_SYSCALL    = 157
	PR_SET_PDEATHSIG = 1
)

func ShutdownOnParentDeath(parentPid int) {
	_, _, errno := syscall.Syscall(uintptr(PRCTL_SYSCALL), uintptr(PR_SET_PDEATHSIG), uintptr(syscall.SIGKILL), 0)
	if errno != 0 {
		os.Exit(127 + int(errno))
	}
	// One last check... there is a possibility that the parent died right before the syscall was sent
	if os.Getppid() != parentPid {
		os.Exit(1)
	}
}
