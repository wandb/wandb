package monitor

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"syscall"

	"github.com/shirou/gopsutil/v4/process"
)

// openWandbFiles returns the .wandb files the process holds open for
// writing, read from /proc/<pid>/fd and fdinfo, which are only readable for
// the current user's processes without root.
func openWandbFiles(proc *process.Process) []string {
	files, err := proc.OpenFiles()
	if err != nil {
		return nil
	}
	var paths []string
	for _, file := range files {
		if isWandbFile(file.Path) && openedForWriting(proc.Pid, file.Fd) {
			paths = append(paths, file.Path)
		}
	}
	return paths
}

// openedForWriting reports whether the descriptor's open flags in
// /proc/<pid>/fdinfo/<fd> include write access.
func openedForWriting(pid int32, fd uint64) bool {
	data, err := os.ReadFile(fmt.Sprintf("/proc/%d/fdinfo/%d", pid, fd))
	if err != nil {
		return false
	}
	for line := range strings.Lines(string(data)) {
		if flags, ok := strings.CutPrefix(line, "flags:"); ok {
			v, err := strconv.ParseUint(strings.TrimSpace(flags), 8, 32)
			return err == nil && v&syscall.O_ACCMODE != syscall.O_RDONLY
		}
	}
	return false
}
