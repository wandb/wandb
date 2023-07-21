package monitor

import (
	"sync"

	"github.com/shirou/gopsutil/v3/mem"
	"github.com/wandb/wandb/nexus/pkg/observability"
	"github.com/wandb/wandb/nexus/pkg/service"
)

// Metrics

// MemoryPercent is total system memory usage in percent
type MemoryPercent struct {
	name    string
	samples []float64
	mutex   sync.RWMutex
}

func (mp *MemoryPercent) Name() string { return mp.name }

func (mp *MemoryPercent) Sample() {
	// implementation of sample goes here
	virtualMem, _ := mem.VirtualMemory()
	mp.samples = append(mp.samples, virtualMem.UsedPercent)
}

func (mp *MemoryPercent) Clear() {
	// implementation of clear goes here
	mp.mutex.RLock()
	defer mp.mutex.RUnlock()

	mp.samples = []float64{}
}

func (mp *MemoryPercent) Aggregate() float64 {
	// return sum(mp.samples) / float64(len(mp.samples))
	mp.mutex.RLock()
	defer mp.mutex.RUnlock()

	return Average(mp.samples)
}

// MemoryAvailable is total system memory available in MB
type MemoryAvailable struct {
	name    string
	samples []float64
	mutex   sync.RWMutex
}

func (mp *MemoryAvailable) Name() string { return mp.name }

func (mp *MemoryAvailable) Sample() {
	// implementation of sample goes here
	virtualMem, _ := mem.VirtualMemory()
	mp.samples = append(mp.samples, float64(virtualMem.Available)/1024/1024)
}

func (mp *MemoryAvailable) Clear() {
	// implementation of clear goes here
	mp.mutex.RLock()
	defer mp.mutex.RUnlock()

	mp.samples = []float64{}
}

func (mp *MemoryAvailable) Aggregate() float64 {
	// return sum(mp.samples) / float64(len(mp.samples))
	mp.mutex.RLock()
	defer mp.mutex.RUnlock()

	return Average(mp.samples)
}

// Asset

type Memory struct {
	name           string
	metrics        []Metric
	metricsMonitor *MetricsMonitor
}

func NewMemory(
	settings *service.Settings,
	logger *observability.NexusLogger,
	outChan chan<- *service.Record,
) *Memory {
	metrics := []Metric{
		&MemoryPercent{
			name:    "memory_percent",
			samples: []float64{},
		},
		&MemoryAvailable{
			name:    "proc.memory.availableMB",
			samples: []float64{},
		},
	}

	metricsMonitor := NewMetricsMonitor(
		metrics,
		settings,
		logger,
		outChan,
	)

	return &Memory{
		name:           "memory",
		metrics:        metrics,
		metricsMonitor: metricsMonitor,
	}
}

func (m *Memory) Name() string { return m.name }

func (m *Memory) Metrics() []Metric { return m.metrics }

func (m *Memory) IsAvailable() bool { return true }

func (m *Memory) Start() {
	m.metricsMonitor.wg.Add(1)

	go func() {
		m.metricsMonitor.Monitor()
		m.metricsMonitor.wg.Done()
	}()
}

func (m *Memory) Stop() { m.metricsMonitor.Stop() }

func (m *Memory) Probe() map[string]map[string]interface{} {
	info := make(map[string]map[string]interface{})
	virtualMem, _ := mem.VirtualMemory()
	info["memory"]["total"] = virtualMem.Total / 1024 / 1024 / 1024
	return info
}
