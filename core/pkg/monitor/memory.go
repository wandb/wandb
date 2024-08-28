package monitor

import (
	"errors"

	"github.com/shirou/gopsutil/v4/mem"
	"github.com/shirou/gopsutil/v4/process"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type Memory struct {
	name string
	pid  int32
}

func NewMemory(pid int32) *Memory {
	return &Memory{name: "memory", pid: pid}
}

func (m *Memory) Name() string { return m.name }

func (m *Memory) Sample() (map[string]any, error) {
	metrics := make(map[string]any)
	var errs []error

	virtualMem, err := mem.VirtualMemory()

	if err != nil {
		errs = append(errs, err)
	} else {
		// total system memory usage in percent
		metrics["memory_percent"] = virtualMem.UsedPercent
		// total system memory available in MB
		metrics["proc.memory.availableMB"] = float64(virtualMem.Available) / 1024 / 1024
	}

	// process-related metrics
	proc := process.Process{Pid: m.pid}
	procMem, err := proc.MemoryInfo()
	if err != nil {
		errs = append(errs, err)
	} else {
		// process memory usage in MB
		metrics["proc.memory.rssMB"] = float64(procMem.RSS) / 1024 / 1024
		// process memory usage in percent
		// vertualMem.Total should not be nil
		if virtualMem != nil {
			metrics["proc.memory.percent"] = float64(procMem.RSS) / float64(virtualMem.Total) * 100
		}
	}

	return metrics, errors.Join(errs...)
}

func (m *Memory) IsAvailable() bool { return true }

func (m *Memory) Probe() *spb.MetadataRequest {
	virtualMem, err := mem.VirtualMemory()
	if err != nil {
		return nil
	}
	// total := virtualMem.Total / 1024 / 1024 / 1024
	total := virtualMem.Total

	return &spb.MetadataRequest{
		Memory: &spb.MemoryInfo{
			Total: total,
		},
	}
}
