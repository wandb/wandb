package monitor

import (
	"fmt"
	"sync"

	"github.com/shirou/gopsutil/v3/cpu"

	"github.com/wandb/wandb/nexus/pkg/service"

	"github.com/shirou/gopsutil/v3/process"
)

type CPU struct {
	name     string
	metrics  map[string][]float64
	settings *service.Settings
	mutex    sync.RWMutex
}

func NewCPU(settings *service.Settings) *CPU {
	metrics := map[string][]float64{}

	processor := &CPU{
		name:     "cpu",
		metrics:  metrics,
		settings: settings,
	}

	return processor
}

func (c *CPU) Name() string { return c.name }

func (c *CPU) SampleMetrics() {
	c.mutex.RLock()
	defer c.mutex.RUnlock()

	// process-related metrics
	proc := process.Process{Pid: int32(c.settings.XStatsPid.GetValue())}
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
	c.mutex.RLock()
	defer c.mutex.RUnlock()

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
	c.mutex.RLock()
	defer c.mutex.RUnlock()

	c.metrics = map[string][]float64{}
}

func (c *CPU) IsAvailable() bool { return true }

func (c *CPU) Probe() map[string]map[string]interface{} {
	info := make(map[string]map[string]interface{})
	// todo: add cpu info
	return info
}
