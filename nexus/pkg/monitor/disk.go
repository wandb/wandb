package monitor

import (
	"sync"

	"github.com/shirou/gopsutil/v3/disk"

	"github.com/wandb/wandb/nexus/pkg/service"
)

type Disk struct {
	name     string
	metrics  map[string][]float64
	settings *service.Settings
	mutex    sync.RWMutex
}

func NewDisk(settings *service.Settings) *Disk {
	metrics := map[string][]float64{}

	d := &Disk{
		name:     "disk",
		metrics:  metrics,
		settings: settings,
	}

	return d
}

func (d *Disk) Name() string { return d.name }

func (d *Disk) SampleMetrics() {
	d.mutex.RLock()
	defer d.mutex.RUnlock()

	usage, err := disk.Usage("/")
	if err == nil {
		// used disk space as a percentage
		d.metrics["disk"] = append(
			d.metrics["disk"],
			usage.UsedPercent,
		)
	}

	// todo: IO counters
	// ioCounters, err := disk.IOCounters("/")
}

func (d *Disk) AggregateMetrics() map[string]float64 {
	d.mutex.RLock()
	defer d.mutex.RUnlock()

	aggregates := make(map[string]float64)
	for metric, samples := range d.metrics {
		if len(samples) > 0 {
			aggregates[metric] = samples[len(samples)-1]
		}
	}
	return aggregates
}

func (d *Disk) ClearMetrics() {
	d.mutex.RLock()
	defer d.mutex.RUnlock()

	d.metrics = map[string][]float64{}
}

func (d *Disk) IsAvailable() bool { return true }

func (d *Disk) Probe() map[string]map[string]interface{} {
	info := make(map[string]map[string]interface{})
	usage, err := disk.Usage("/")
	if err == nil {
		info["disk"]["total"] = usage.Total / 1024 / 1024 / 1024
		info["disk"]["used"] = usage.Used / 1024 / 1024 / 1024
	}
	return info
}
