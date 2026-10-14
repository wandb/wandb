package monitor

import (
	"time"

	"github.com/shirou/gopsutil/v4/process"
)

// processNameSettle is how long after a process starts its name is read on
// every sample: a forked child carries its parent's name until it execs.
const processNameSettle = 10 * time.Second

// ProcessStat is one process's share of the CPU since the previous sample,
// in percent of one core, and its resident memory in bytes.
type ProcessStat struct {
	PID        int32
	PPID       int32
	Name       string
	CPUPercent float64
	RSS        uint64
}

// Processes samples every process on the host.
//
// It keeps a handle per PID between samples so that CPU shares are measured
// over the sampling interval; a PID taken over by a new process gets a fresh
// handle. Only the standalone system monitor uses it.
type Processes struct {
	handles map[int32]*processHandle
}

// processHandle is a process and its name, which macOS answers with a
// command-line lookup and so is not read on every sample.
type processHandle struct {
	*process.Process
	name string
}

func NewProcesses() *Processes {
	return &Processes{handles: make(map[int32]*processHandle)}
}

// Sample returns the processes whose CPU and memory the current user can
// read. A process seen for the first time reports no CPU share yet.
func (p *Processes) Sample() ([]ProcessStat, error) {
	pids, err := process.Pids()
	if err != nil {
		return nil, err
	}

	handles := make(map[int32]*processHandle, len(pids))
	stats := make([]ProcessStat, 0, len(pids))
	for _, pid := range pids {
		proc := &process.Process{Pid: pid}
		start, err := proc.CreateTime()
		if err != nil {
			continue
		}
		handle := p.handles[pid]
		if handle != nil {
			if cachedStart, _ := handle.CreateTime(); cachedStart != start {
				handle = nil
			}
		}
		if handle == nil {
			handle = &processHandle{Process: proc}
		}
		if handle.name == "" || time.Since(time.UnixMilli(start)) < processNameSettle {
			handle.name, _ = handle.Name()
		}
		handles[pid] = handle

		cpuPercent, err := handle.Percent(0)
		if err != nil {
			continue
		}
		mem, err := handle.MemoryInfo()
		if err != nil || mem.RSS == 0 {
			continue
		}
		ppid, _ := handle.Ppid()
		stats = append(stats, ProcessStat{
			PID:        pid,
			PPID:       ppid,
			Name:       handle.name,
			CPUPercent: cpuPercent,
			RSS:        mem.RSS,
		})
	}
	p.handles = handles
	return stats, nil
}
