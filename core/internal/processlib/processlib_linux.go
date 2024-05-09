package processlib

import (
	"os"
	"syscall"
)

const (
	// Linux syscall for prctl, see x/sys/unix SYS_PRCTL
	PRCTL_SYSCALL = 157
	// Set the parent-death signal of the calling process, see uapi/linux/prctl.h
	PR_SET_PDEATHSIG = 1
)

func ShutdownOnParentExit(parentPid int) bool {
	_, _, errno := syscall.Syscall(
		uintptr(PRCTL_SYSCALL), uintptr(PR_SET_PDEATHSIG), uintptr(syscall.SIGKILL), 0)
	if errno != 0 {
		// Exit code is arbitrary as parent process is gone.
		// Encode syscall error number in upper bits for debugging.
		os.Exit(127 + int(errno))
	}
	// Check again because the process could have exited right before the syscall was made
	if os.Getppid() != parentPid {
		// Exit code is arbitrary as parent process is gone.
		os.Exit(1)
	}
	return true
}
