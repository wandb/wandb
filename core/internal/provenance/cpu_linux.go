//go:build linux

package provenance

import (
	"runtime"

	"golang.org/x/sys/unix"
)

func collectorCPU() func() *int64 {
	runtime.LockOSThread()
	var before unix.Rusage
	beforeErr := unix.Getrusage(unix.RUSAGE_THREAD, &before)
	return func() *int64 {
		defer runtime.UnlockOSThread()
		var after unix.Rusage
		if unix.Getrusage(unix.RUSAGE_THREAD, &after) != nil || beforeErr != nil {
			return nil
		}
		duration := after.Utime.Nano() + after.Stime.Nano() - before.Utime.Nano() - before.Stime.Nano()
		return &duration
	}
}
