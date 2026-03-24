package leet

import (
	"fmt"
	"maps"
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"time"

	"golang.org/x/sync/errgroup"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/observability"
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

// SymonSampler produces live StatsMsg updates using the shared monitor
// resources.
//
// Each call to Sample collects one point-in-time snapshot across the available
// system, GPU, and TPU resources. The resulting metrics are aligned to a single
// wall-clock timestamp before they are merged into one StatsMsg for the UI.
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
		}))

	gpuManager := monitor.NewGPUResourceManager(false)
	gpu, err := monitor.NewGPU(gpuManager, 0, nil)
	if err != nil {
		logger.Debug(fmt.Sprintf("symon: gpu monitor unavailable: %v", err))
	} else if gpu != nil {
		sampler.resources = append(sampler.resources, gpu)
	}

	if tpu := monitor.NewTPU(sampler.logger); tpu != nil {
		sampler.resources = append(sampler.resources, tpu)
	}

	return sampler
}

// Interval reports the configured delay between sampling passes.
func (s *SymonSampler) Interval() time.Duration {
	return s.interval
}

// Sample gathers one aligned snapshot across all resources.
func (s *SymonSampler) Sample() StatsMsg {
	now := time.Now()
	out := StatsMsg{
		Timestamp: now.Unix(),
		Metrics:   make(map[string]float64),
	}

	var mu sync.Mutex
	var g errgroup.Group

	for _, resource := range s.resources {
		g.Go(func() error {
			record, err := resource.Sample()
			if err != nil {
				s.logSamplingError(err)
				return nil
			}
			if record == nil {
				return nil
			}

			// Align all metrics from one sampling pass to the same wall-clock tick.
			record.Timestamp = timestamppb.New(now)

			msg, ok := ParseStats("", record).(StatsMsg)
			if !ok || len(msg.Metrics) == 0 {
				return nil
			}

			mu.Lock()
			maps.Copy(out.Metrics, msg.Metrics)
			mu.Unlock()
			return nil
		})
	}

	_ = g.Wait()
	return out
}

// Cleanup releases any resources that need explicit shutdown, such as the GPU
// sidecar process managed by the monitor package.
func (s *SymonSampler) Cleanup() {
	for _, resource := range s.resources {
		if closer, ok := resource.(interface{ Close() }); ok {
			closer.Close()
		}
	}
}

// logSamplingError routes sampling failures either to Sentry or debug logs,
// depending on whether the monitor package considers them expected.
func (s *SymonSampler) logSamplingError(err error) {
	if monitor.ShouldCaptureSamplingError(err) {
		s.logger.CaptureError(fmt.Errorf("symon: sampling error: %v", err))
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
