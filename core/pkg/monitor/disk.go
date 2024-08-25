package monitor

import (
	"errors"
	"fmt"
	"strings"
	"sync"

	"github.com/shirou/gopsutil/v4/disk"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type Disk struct {
	name      string
	metrics   map[string][]float64
	diskPaths []string
	mutex     sync.RWMutex
	readInit  int
	writeInit int
}

func NewDisk(diskPaths []string) *Disk {
	d := &Disk{
		name:      "disk",
		metrics:   map[string][]float64{},
		diskPaths: diskPaths,
	}

	// todo: collect metrics for each disk
	ioCounters, err := disk.IOCounters()
	if err == nil {
		d.readInit = int(ioCounters["disk0"].ReadBytes)
		d.writeInit = int(ioCounters["disk0"].WriteBytes)
	}

	return d
}

func (d *Disk) Name() string { return d.name }

func (d *Disk) SampleMetrics() error {
	d.mutex.Lock()
	defer d.mutex.Unlock()

	var errs []error

	for _, diskPath := range d.diskPaths {
		usage, err := disk.Usage(diskPath)
		if err != nil {
			errs = append(errs, err)
		} else {
			// used disk space as a percentage
			keyPercent := fmt.Sprintf("disk.%s.usagePercent", diskPath)
			d.metrics[keyPercent] = append(
				d.metrics[keyPercent],
				usage.UsedPercent,
			)
			// used disk space in GB
			keyGB := fmt.Sprintf("disk.%s.usageGB", diskPath)
			d.metrics[keyGB] = append(
				d.metrics[keyGB],
				float64(usage.Used)/1024/1024/1024,
			)
		}
	}

	// IO counters
	ioCounters, err := disk.IOCounters()
	if err != nil {
		// do not log "not implemented yet" errors
		if !strings.Contains(err.Error(), "not implemented yet") {
			errs = append(errs, err)
		}
	} else {
		// MB read/written
		d.metrics["disk.in"] = append(
			d.metrics["disk.in"],
			float64(int(ioCounters["disk0"].ReadBytes)-d.readInit)/1024/1024,
		)
		d.metrics["disk.out"] = append(
			d.metrics["disk.out"],
			float64(int(ioCounters["disk0"].WriteBytes)-d.writeInit)/1024/1024,
		)
	}

	return errors.Join(errs...)
}

func (d *Disk) AggregateMetrics() map[string]float64 {
	d.mutex.Lock()
	defer d.mutex.Unlock()

	aggregates := make(map[string]float64)
	for metric, samples := range d.metrics {
		if len(samples) > 0 {
			aggregates[metric] = samples[len(samples)-1]
		}
	}
	return aggregates
}

func (d *Disk) ClearMetrics() {
	d.mutex.Lock()
	defer d.mutex.Unlock()

	d.metrics = map[string][]float64{}
}

func (d *Disk) IsAvailable() bool { return true }

func (d *Disk) Probe() *spb.MetadataRequest {
	info := &spb.MetadataRequest{
		Disk: make(map[string]*spb.DiskInfo),
	}
	for _, diskPath := range d.diskPaths {
		usage, err := disk.Usage(diskPath)
		if err != nil {
			continue
		}
		info.Disk[diskPath] = &spb.DiskInfo{
			Total: usage.Total,
			Used:  usage.Used,
		}
	}
	return info
}
