package monitor

import (
	"sync"

	"github.com/shirou/gopsutil/v3/mem"
)

type Memory struct {
	name    string
	metrics map[string][]float64
	mutex   sync.RWMutex
}

func NewMemory() *Memory {
	metrics := map[string][]float64{}

	memory := &Memory{
		name:    "memory",
		metrics: metrics,
	}

	return memory
}

func (m *Memory) Name() string { return m.name }

func (m *Memory) SampleMetrics() {
	m.mutex.RLock()
	defer m.mutex.RUnlock()

	virtualMem, _ := mem.VirtualMemory()

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

func (m *Memory) AggregateMetrics() map[string]float64 {
	m.mutex.RLock()
	defer m.mutex.RUnlock()

	aggregates := make(map[string]float64)
	for metric, samples := range m.metrics {
		if len(samples) > 0 {
			aggregates[metric] = Average(samples)
		}
	}
	return aggregates
}

func (m *Memory) ClearMetrics() {
	m.mutex.RLock()
	defer m.mutex.RUnlock()

	m.metrics = map[string][]float64{}
}

func (m *Memory) IsAvailable() bool { return true }

func (m *Memory) Probe() map[string]map[string]interface{} {
	info := make(map[string]map[string]interface{})
	virtualMem, _ := mem.VirtualMemory()
	info["memory"]["total"] = virtualMem.Total / 1024 / 1024 / 1024
	return info
}
