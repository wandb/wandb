//go:build linux

package kittyshm

import (
	"golang.org/x/sys/unix"
	"os"
)

func openSHM(name string, create bool) (*os.File, error) {
	flags := os.O_RDONLY
	if create {
		flags = os.O_CREATE | os.O_EXCL | os.O_RDWR
	}
	return os.OpenFile("/dev/shm"+name, flags, 0600)
}
func unlinkSHM(name string) error { return os.Remove("/dev/shm" + name) }

// Reserve tmpfs pages before mmap so a full /dev/shm returns ENOSPC here,
// rather than delivering SIGBUS when fill touches an unallocated page.
func reserveBacking(f *os.File, size int) error {
	return unix.Fallocate(int(f.Fd()), 0, 0, int64(size))
}
