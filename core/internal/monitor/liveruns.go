package monitor

import (
	"cmp"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/shirou/gopsutil/v4/process"
)

// LiveRun is a W&B run whose wandb-core service on this machine holds its
// transaction log open.
type LiveRun struct {
	// Path is the run's .wandb transaction log.
	Path string

	// PID is the wandb-core service process writing the log.
	PID int32

	// ClientPID is the process that started the run, which the service was
	// told to watch. Zero when unknown.
	ClientPID int32

	// Since is when the service started.
	Since time.Time
}

// SampleLiveRuns returns the runs written by the wandb-core services among
// procs, newest first.
//
// It looks only at processes the current user owns, recognizes a service by
// its executable name and the --port-filename flag the client starts it
// with, and lists the .wandb files it holds open for writing. It never reads
// a process's environment and never signals one.
func SampleLiveRuns(procs []ProcessStat) []LiveRun {
	uid := os.Getuid()
	var runs []LiveRun
	for _, stat := range procs {
		if !isWandbCore(stat.Name) {
			continue
		}
		proc, err := process.NewProcess(stat.PID)
		if err != nil || !ownedBy(proc, uid) {
			continue
		}
		args, err := proc.CmdlineSlice()
		if err != nil || !slices.Contains(args, "--port-filename") {
			continue
		}
		started, _ := proc.CreateTime()
		for _, path := range openWandbFiles(proc) {
			runs = append(runs, LiveRun{
				Path:      path,
				PID:       stat.PID,
				ClientPID: flagValue(args, "--pid"),
				Since:     time.UnixMilli(started),
			})
		}
	}
	slices.SortFunc(runs, func(a, b LiveRun) int {
		return cmp.Or(b.Since.Compare(a.Since), strings.Compare(a.Path, b.Path))
	})
	return runs
}

// isWandbCore reports whether a process name is the wandb-core binary.
func isWandbCore(name string) bool {
	return strings.TrimSuffix(name, ".exe") == "wandb-core"
}

// ownedBy reports whether the process belongs to the user.
func ownedBy(proc *process.Process, uid int) bool {
	uids, err := proc.Uids()
	return err == nil && len(uids) > 0 && int(uids[0]) == uid
}

// flagValue returns the integer following flag in args, or zero.
func flagValue(args []string, flag string) int32 {
	i := slices.Index(args, flag)
	if i < 0 || i+1 >= len(args) {
		return 0
	}
	v, err := strconv.Atoi(args[i+1])
	if err != nil {
		return 0
	}
	return int32(v)
}

// isWandbFile reports whether path is an existing .wandb transaction log.
func isWandbFile(path string) bool {
	if filepath.Ext(path) != ".wandb" {
		return false
	}
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular()
}
