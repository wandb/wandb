//go:build !windows

package uploader

import (
	"golang.org/x/sys/unix"
)

func getRlimit(defaultValue int32) int32 {
	if defaultValue > 0 {
		return defaultValue
	}
	var rlim unix.Rlimit
	err := unix.Getrlimit(unix.RLIMIT_NOFILE, &rlim)
	if err != nil {
		return defaultConcurrencyLimit
	}
	// todo: verify this is correct on macos
	return int32(rlim.Cur)
}
