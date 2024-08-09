package monitor

import (
	"fmt"
	"sync"

	"github.com/shirou/gopsutil/v4/cpu"

	"github.com/wandb/wandb/core/pkg/service"

	"github.com/shirou/gopsutil/v4/process"
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

func (c *CPU) SampleMetrics() {
	c.mutex.Lock()
	defer c.mutex.Unlock()

	// process-related metrics
	proc := process.Process{Pid: c.pid}
	// process CPU usage in percent
	procCPU, err := proc.CPUPercent()
	if err == nil {
		// cpu count
		cpuCount, err2 := cpu.Counts(true)
		if err2 == nil {
			c.metrics["cpu"] = append(
				c.metrics["cpu"],
				procCPU/float64(cpuCount),
			)
		} else {
			c.metrics["cpu"] = append(
				c.metrics["cpu"],
				procCPU,
			)
		}
	}
	// number of threads used by process
	procThreads, err := proc.NumThreads()
	if err == nil {
		c.metrics["proc.cpu.threads"] = append(
			c.metrics["proc.cpu.threads"],
			float64(procThreads),
		)
	}

	// total system CPU usage in percent
	utilization, err := cpu.Percent(0, true)
	if err == nil {
		for i, u := range utilization {
			metricName := fmt.Sprintf("cpu.%d.cpu_percent", i)
			c.metrics[metricName] = append(
				c.metrics[metricName],
				u,
			)
		}
	}
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

func (c *CPU) Probe() *service.MetadataRequest {
	info := service.MetadataRequest{
		Cpu: &service.CpuInfo{},
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
