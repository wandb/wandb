//go:build darwin && cgo

package kittyshm

/*
#include <sys/mman.h>
#include <fcntl.h>
#include <stdlib.h>
static int ntc_shm_open(const char *name, int create) {
 return shm_open(name, create ? O_CREAT | O_EXCL | O_RDWR : O_RDONLY, 0600);
}
*/
import "C"

import (
	"os"
	"unsafe"
)

func openSHM(name string, create bool) (*os.File, error) {
	s := C.CString(name)
	defer C.free(unsafe.Pointer(s))
	var c C.int
	if create {
		c = 1
	}
	fd, err := C.ntc_shm_open(s, c)
	if fd < 0 {
		return nil, os.NewSyscallError("shm_open", err)
	}
	return os.NewFile(uintptr(fd), name), nil
}

func unlinkSHM(name string) error {
	s := C.CString(name)
	defer C.free(unsafe.Pointer(s))
	rc, err := C.shm_unlink(s)
	if rc != 0 {
		return os.NewSyscallError("shm_unlink", err)
	}
	return nil
}

func reserveBacking(_ *os.File, _ int) error { return nil }
