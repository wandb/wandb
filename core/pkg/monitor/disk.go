package monitor

import (
	"errors"
	"fmt"
	"strings"

	"github.com/shirou/gopsutil/v4/disk"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type Disk struct {
	name      string
	diskPaths []string
	readInit  int
	writeInit int
}

func NewDisk(diskPaths []string) *Disk {
	d := &Disk{
		name:      "disk",
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

func (d *Disk) Sample() (map[string]any, error) {

	metrics := make(map[string]any)
	var errs []error

	for _, diskPath := range d.diskPaths {
		usage, err := disk.Usage(diskPath)
		if err != nil {
			errs = append(errs, err)
		} else {
			// used disk space as a percentage
			metrics[fmt.Sprintf("disk.%s.usagePercent", diskPath)] = usage.UsedPercent
			// used disk space in GB
			metrics[fmt.Sprintf("disk.%s.usageGB", diskPath)] = float64(usage.Used) / 1024 / 1024 / 1024
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
		metrics["disk.in"] = float64(int(ioCounters["disk0"].ReadBytes)-d.readInit) / 1024 / 1024
		metrics["disk.out"] = float64(int(ioCounters["disk0"].WriteBytes)-d.writeInit) / 1024 / 1024
	}

	return metrics, errors.Join(errs...)
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
