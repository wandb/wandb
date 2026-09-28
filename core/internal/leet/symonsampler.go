package leet

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"time"

	"golang.org/x/sync/errgroup"

	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/systemmetrics"
)

// DefaultSymonSamplingInterval is the sampling cadence used by SYMON when the
// caller does not provide an explicit interval.
const DefaultSymonSamplingInterval = 2 * time.Second

// SymonSamplerParams configures a SymonSampler.
type SymonSamplerParams struct {
	// Interval controls the delay between successive sampling passes. Values
	// less than or equal to zero use DefaultSymonSamplingInterval.
	Interval time.Duration

	// Logger receives benign debug messages and noteworthy sampling errors.
	Logger *observability.CoreLogger
}

// SymonSampler produces live SystemMetricsMsg updates using the shared monitor
// resources.
//
// Each call to Sample collects one point-in-time snapshot across the available
// system and accelerator resources. The resulting metrics are aligned to a single
// wall-clock timestamp before they are merged into one SystemMetricsMsg for the UI.
type SymonSampler struct {
	interval  time.Duration
	resources []monitor.Resource
	logger    *observability.CoreLogger
}

func NewSymonSampler(params SymonSamplerParams) *SymonSampler {
	logger := params.Logger
	if logger == nil {
		logger = observability.NewNoOpLogger()
	}

	interval := params.Interval
	if interval <= 0 {
		interval = DefaultSymonSamplingInterval
	}

	sampler := &SymonSampler{
		interval: interval,
		logger:   logger,
	}

	sampler.resources = append(sampler.resources,
		monitor.NewSystem(monitor.SystemParams{
			Pid:              0,
			TrackProcessTree: false,
			DiskPaths:        defaultSymonDiskPaths(),
		}),
		monitor.NewXPU(context.Background(), monitor.NewXPUResourceManager(false), 0, nil),
	)

	return sampler
}

// Interval reports the configured delay between sampling passes.
func (s *SymonSampler) Interval() time.Duration {
	return s.interval
}

// Sample gathers one aligned snapshot across all resources.
func (s *SymonSampler) Sample() SystemMetricsMsg {
	now := time.Now()
	out := SystemMetricsMsg{Timestamp: now.Unix()}

	var mu sync.Mutex
	var g errgroup.Group

	for _, resource := range s.resources {
		g.Go(func() error {
			// Hardware sampling paths are known to panic (see SystemMonitor).
			// A panic here would crash the whole TUI: bubbletea's panic
			// recovery does not cover goroutines spawned by commands.
			defer func() {
				if r := recover(); r != nil {
					s.logger.CaptureError(
						"leet",
						fmt.Errorf("symon: panic sampling resource: %v", r),
					)
				}
			}()

			record, err := resource.Sample()
			if err != nil {
				s.logSamplingError(err)
				return nil
			}
			if record == nil {
				return nil
			}

			samples := systemmetrics.Samples(record)
			if len(samples) == 0 {
				return nil
			}

			// Align all metrics from one sampling pass to the same wall-clock tick.
			mu.Lock()
			out.Samples = append(out.Samples, samples...)
			mu.Unlock()
			return nil
		})
	}

	_ = g.Wait()
	return out
}

// Cleanup releases any resources that need explicit shutdown, such as the wandb-xpu
// sidecar process managed by the monitor package.
func (s *SymonSampler) Cleanup() {
	for _, resource := range s.resources {
		if closer, ok := resource.(interface{ Close() }); ok {
			closer.Close()
		}
	}
}

// logSamplingError captures unexpected sampling failures and debug-logs
// expected ones.
func (s *SymonSampler) logSamplingError(err error) {
	if monitor.ShouldCaptureSamplingError(err) {
		s.logger.CaptureError(
			"leet",
			fmt.Errorf("symon: sampling error: %v", err),
		)
		return
	}
	s.logger.Debug(fmt.Sprintf("symon: benign sampling error: %v", err))
}

// defaultSymonDiskPaths returns the filesystem roots that SYMON should monitor
// for disk usage and I/O.
//
// On Unix-like systems, monitoring "/" provides a sensible host-wide default.
// On Windows, disk usage APIs operate on volume roots, so we derive the current
// working drive and monitor that volume root instead.
func defaultSymonDiskPaths() []string {
	if runtime.GOOS != "windows" {
		return []string{"/"}
	}

	wd, err := os.Getwd()
	if err != nil {
		return nil
	}
	volume := filepath.VolumeName(wd)
	if volume == "" {
		return nil
	}
	return []string{volume + string(filepath.Separator)}
}
