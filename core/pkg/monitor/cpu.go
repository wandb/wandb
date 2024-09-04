package monitor

import (
	"errors"
	"fmt"
	"strings"

	"github.com/shirou/gopsutil/v4/cpu"
	"github.com/shirou/gopsutil/v4/process"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type CPU struct {
	name string
	pid  int32
}

func NewCPU(pid int32) *CPU {
	return &CPU{name: "cpu", pid: pid}
}

func (c *CPU) Name() string { return c.name }

func (c *CPU) Sample() (map[string]any, error) {
	metrics := make(map[string]any)
	var errs []error

	// process-related metrics
	proc := process.Process{Pid: c.pid}
	// process CPU usage in percent
	procCPU, err := proc.CPUPercent()
	if err != nil {
		errs = append(errs, err)
	} else {
		// cpu count
		cpuCount, err := cpu.Counts(true)
		if err != nil {
			errs = append(errs, err)
			// if we can't get the cpu count, we'll just use the raw value
			metrics["cpu"] = procCPU
		} else {
			metrics["cpu"] = procCPU / float64(cpuCount)
		}
	}
	// number of threads used by process
	procThreads, err := proc.NumThreads()
	if err != nil {
		errs = append(errs, err)
	} else {
		metrics["proc.cpu.threads"] = float64(procThreads)
	}

	// total system CPU usage in percent
	utilization, err := cpu.Percent(0, true)
	if err != nil {
		// do not log "not implemented yet" errors
		if !strings.Contains(err.Error(), "not implemented yet") {
			errs = append(errs, err)
		}
	} else {
		for i, u := range utilization {
			metrics[fmt.Sprintf("cpu.%d.cpu_percent", i)] = u
		}
	}

	return metrics, errors.Join(errs...)
}
func (c *CPU) IsAvailable() bool { return true }

func (c *CPU) Probe() *spb.MetadataRequest {
	info := spb.MetadataRequest{
		Cpu: &spb.CpuInfo{},
	}

	// todo: add more info from cpuInfo
	// cpuInfo, err := cpu.Info()

	cpuCount, err := cpu.Counts(false)
	if err == nil {
		info.CpuCount = uint32(cpuCount)
		info.Cpu.Count = uint32(cpuCount)
	}
	cpuCountLogical, err2 := cpu.Counts(true)
	if err2 == nil {
		info.CpuCountLogical = uint32(cpuCountLogical)
		info.Cpu.CountLogical = uint32(cpuCountLogical)
	}
	// todo: add cpu frequency info per core
	return &info
}
