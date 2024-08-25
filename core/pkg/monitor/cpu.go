package monitor

import (
	"errors"
	"fmt"
	"strings"
	"sync"

	"github.com/shirou/gopsutil/v4/cpu"
	"github.com/shirou/gopsutil/v4/process"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type CPU struct {
	name    string
	metrics map[string][]float64
	pid     int32
	mutex   sync.RWMutex
}

func NewCPU(pid int32) *CPU {
	return &CPU{
		name:    "cpu",
		metrics: map[string][]float64{},
		pid:     pid,
	}
}

func (c *CPU) Name() string { return c.name }

func (c *CPU) SampleMetrics() error {
	c.mutex.Lock()
	defer c.mutex.Unlock()

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
			c.metrics["cpu"] = append(
				c.metrics["cpu"],
				procCPU,
			)
		} else {
			c.metrics["cpu"] = append(
				c.metrics["cpu"],
				procCPU/float64(cpuCount),
			)
		}
	}
	// number of threads used by process
	procThreads, err := proc.NumThreads()
	if err != nil {
		errs = append(errs, err)
	} else {
		c.metrics["proc.cpu.threads"] = append(
			c.metrics["proc.cpu.threads"],
			float64(procThreads),
		)
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
			metricName := fmt.Sprintf("cpu.%d.cpu_percent", i)
			c.metrics[metricName] = append(
				c.metrics[metricName],
				u,
			)
		}
	}

	return errors.Join(errs...)
}

func (c *CPU) AggregateMetrics() map[string]float64 {
	c.mutex.Lock()
	defer c.mutex.Unlock()

	aggregates := make(map[string]float64)
	for metric, samples := range c.metrics {
		if len(samples) > 0 {
			if metric == "proc.cpu.threads" {
				aggregates[metric] = samples[len(samples)-1]
				continue
			}
			aggregates[metric] = Average(samples)
		}
	}
	return aggregates
}

func (c *CPU) ClearMetrics() {
	c.mutex.Lock()
	defer c.mutex.Unlock()

	c.metrics = map[string][]float64{}
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
