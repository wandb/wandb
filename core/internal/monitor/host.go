package monitor

import (
	"context"
	"errors"
	"runtime"

	"github.com/shirou/gopsutil/v4/host"
	"github.com/shirou/gopsutil/v4/load"
	"github.com/shirou/gopsutil/v4/mem"
	"google.golang.org/protobuf/types/known/timestamppb"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Host samples host-wide facts that runs do not collect: the load average,
// the uptime and swap usage.
//
// Only the standalone system monitor registers it.
type Host struct{}

func NewHost() *Host {
	return &Host{}
}

func (h *Host) Sample() (*spb.StatsRecord, error) {
	metrics := make(map[string]any)
	var errs []error

	if avg, err := load.Avg(); err == nil {
		metrics["system.load1"] = avg.Load1
		metrics["system.load5"] = avg.Load5
		metrics["system.load15"] = avg.Load15
	} else {
		errs = append(errs, err)
	}

	if uptime, err := host.Uptime(); err == nil {
		metrics["system.uptime"] = float64(uptime)
	} else {
		errs = append(errs, err)
	}

	// On Apple Silicon the wandb-xpu sidecar reports swap.
	if runtime.GOOS != "darwin" || runtime.GOARCH != "arm64" {
		if swap, err := mem.SwapMemory(); err == nil {
			metrics["swap.used"] = float64(swap.Used)
			metrics["swap.used_percent"] = swap.UsedPercent
		} else {
			errs = append(errs, err)
		}
	}

	if len(metrics) == 0 {
		return nil, errors.Join(errs...)
	}
	return marshal(metrics, timestamppb.Now()), errors.Join(errs...)
}

func (h *Host) Probe(context.Context) *spb.EnvironmentRecord {
	return nil
}
