package monitor

import (
	"fmt"
	"sync"

	"github.com/shirou/gopsutil/v3/disk"

	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

type Disk struct {
	name      string
	metrics   map[string][]float64
	settings  *pb.Settings
	mutex     sync.RWMutex
	readInit  int
	writeInit int
}

func NewDisk(settings *pb.Settings) *Disk {
	d := &Disk{
		name:     "disk",
		metrics:  map[string][]float64{},
		settings: settings,
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

func (d *Disk) SampleMetrics() {
	d.mutex.RLock()
	defer d.mutex.RUnlock()

	for _, diskPath := range d.settings.XStatsDiskPaths.GetValue() {
		usage, err := disk.Usage(diskPath)
		if err == nil {
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
	if err == nil {
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

func (d *Disk) Probe() *pb.MetadataRequest {
	info := &pb.MetadataRequest{
		Disk: make(map[string]*pb.DiskInfo),
	}
	for _, diskPath := range d.settings.XStatsDiskPaths.GetValue() {
		usage, err := disk.Usage(diskPath)
		if err != nil {
			continue
		}
		info.Disk[diskPath] = &pb.DiskInfo{
			Total: usage.Total,
			Used:  usage.Used,
		}
	}
	return info
}
