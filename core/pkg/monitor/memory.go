package monitor

import (
	"sync"

	"github.com/wandb/wandb/core/pkg/service"

	"github.com/shirou/gopsutil/v3/mem"
	"github.com/shirou/gopsutil/v3/process"
)

type Memory struct {
	name     string
	metrics  map[string][]float64
	settings *service.Settings
	mutex    sync.RWMutex
}

func NewMemory(settings *service.Settings) *Memory {
	return &Memory{
		name:     "memory",
		metrics:  map[string][]float64{},
		settings: settings,
	}
}

func (m *Memory) Name() string { return m.name }

func (m *Memory) SampleMetrics() {
	m.mutex.Lock()
	defer m.mutex.Unlock()

	virtualMem, err := mem.VirtualMemory()

	if err == nil {
		// total system memory usage in percent
		m.metrics["memory_percent"] = append(
			m.metrics["memory_percent"],
			virtualMem.UsedPercent,
		)
		// total system memory available in MB
		m.metrics["proc.memory.availableMB"] = append(
			m.metrics["proc.memory.availableMB"],
			float64(virtualMem.Available)/1024/1024,
		)
	}

	// process-related metrics
	proc := process.Process{Pid: m.settings.XStatsPid.GetValue()}
	procMem, err := proc.MemoryInfo()
	if err == nil {
		// process memory usage in MB
		m.metrics["proc.memory.rssMB"] = append(
			m.metrics["proc.memory.rssMB"],
			// this sometimes panics:
			float64(procMem.RSS)/1024/1024,
		)
		// process memory usage in percent
		m.metrics["proc.memory.percent"] = append(
			m.metrics["proc.memory.percent"],
			float64(procMem.RSS)/float64(virtualMem.Total)*100,
		)
	}
}

func (m *Memory) AggregateMetrics() map[string]float64 {
	m.mutex.Lock()
	defer m.mutex.Unlock()

	aggregates := make(map[string]float64)
	for metric, samples := range m.metrics {
		if len(samples) > 0 {
			aggregates[metric] = Average(samples)
		}
	}
	return aggregates
}

func (m *Memory) ClearMetrics() {
	m.mutex.Lock()
	defer m.mutex.Unlock()

	m.metrics = map[string][]float64{}
}

func (m *Memory) IsAvailable() bool { return true }

func (m *Memory) Probe() *service.MetadataRequest {
	virtualMem, err := mem.VirtualMemory()
	if err != nil {
		return nil
	}
	// total := virtualMem.Total / 1024 / 1024 / 1024
	total := virtualMem.Total

	return &service.MetadataRequest{
		Memory: &service.MemoryInfo{
			Total: total,
		},
	}
}
