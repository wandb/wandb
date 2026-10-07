package monitor

import (
	"bytes"
	"sync"
	"unsafe"

	"github.com/ebitengine/purego"
	"github.com/shirou/gopsutil/v4/process"
)

// libproc flavors and constants from sys/proc_info.h and sys/fcntl.h.
const (
	procPIDListFDs         = 1
	procPIDFDVnodePathInfo = 2
	proxFDTypeVnode        = 1
	fwrite                 = 0x2
)

// procFDInfo mirrors struct proc_fdinfo.
type procFDInfo struct {
	FD   int32
	Type uint32
}

// vnodeFDInfoWithPath mirrors struct vnode_fdinfowithpath: a
// proc_fileinfo, an opaque vnode_info and the path.
type vnodeFDInfoWithPath struct {
	openFlags  uint32
	status     uint32
	offset     int64
	fileType   int32
	guardFlags uint32
	vnodeInfo  [152]byte
	path       [1024]byte
}

var libproc struct {
	once      sync.Once
	err       error
	pidInfo   func(pid, flavor int32, arg uint64, buffer unsafe.Pointer, size int32) int32
	pidFDInfo func(pid, fd, flavor int32, buffer unsafe.Pointer, size int32) int32
}

func loadLibproc() error {
	libproc.once.Do(func() {
		handle, err := purego.Dlopen(
			"/usr/lib/libSystem.B.dylib", purego.RTLD_LAZY|purego.RTLD_GLOBAL)
		if err != nil {
			libproc.err = err
			return
		}
		purego.RegisterLibFunc(&libproc.pidInfo, handle, "proc_pidinfo")
		purego.RegisterLibFunc(&libproc.pidFDInfo, handle, "proc_pidfdinfo")
	})
	return libproc.err
}

// openWandbFiles returns the .wandb files the process holds open for
// writing. libproc answers only for the current user's processes without
// root.
func openWandbFiles(proc *process.Process) []string {
	if loadLibproc() != nil {
		return nil
	}
	const fdSize = int32(unsafe.Sizeof(procFDInfo{}))
	size := libproc.pidInfo(proc.Pid, procPIDListFDs, 0, nil, 0)
	if size <= 0 {
		return nil
	}
	fds := make([]procFDInfo, size/fdSize+16)
	size = libproc.pidInfo(
		proc.Pid, procPIDListFDs, 0, unsafe.Pointer(&fds[0]), int32(len(fds))*fdSize)
	if size <= 0 {
		return nil
	}

	var paths []string
	for _, fd := range fds[:size/fdSize] {
		if fd.Type != proxFDTypeVnode {
			continue
		}
		var info vnodeFDInfoWithPath
		want := int32(unsafe.Sizeof(info))
		got := libproc.pidFDInfo(
			proc.Pid, fd.FD, procPIDFDVnodePathInfo, unsafe.Pointer(&info), want)
		if got != want || info.openFlags&fwrite == 0 {
			continue
		}
		path, _, _ := bytes.Cut(info.path[:], []byte{0})
		if isWandbFile(string(path)) {
			paths = append(paths, string(path))
		}
	}
	return paths
}
