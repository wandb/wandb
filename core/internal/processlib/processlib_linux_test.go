package processlib_test

import (
	"os"
	"syscall"
	"testing"
	"unsafe"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/processlib"
)

// prGetPdeathsig reads the parent-death signal, see uapi/linux/prctl.h.
const prGetPdeathsig = 2

func TestShutdownOnParentExit_SetsParentDeathSignal(t *testing.T) {
	require.True(t, processlib.ShutdownOnParentExit(os.Getppid()))

	var signal int32
	_, _, errno := syscall.RawSyscall(
		syscall.SYS_PRCTL,
		prGetPdeathsig,
		uintptr(unsafe.Pointer(&signal)),
		0,
	)
	require.Zero(t, errno)
	require.EqualValues(t, syscall.SIGKILL, signal)
}
