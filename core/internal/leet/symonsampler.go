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

const defaultSymonSamplingInterval = 2 * time.Second

// SymonSampler produces live StatsMsg updates using the shared monitor resources.
type SymonSampler struct {
	interval  time.Duration
	resources []monitor.Resource
	logger    *observability.CoreLogger
}

func NewSymonSampler(logger *observability.CoreLogger) *SymonSampler {
	if logger == nil {
		logger = observability.NewNoOpLogger()
	}

	sampler := &SymonSampler{
		interval: defaultSymonSamplingInterval,
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

func (s *SymonSampler) Interval() time.Duration {
	if s == nil || s.interval <= 0 {
		return defaultSymonSamplingInterval
	}
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

func (s *SymonSampler) Cleanup() {
	if s == nil {
		return
	}
	for _, resource := range s.resources {
		if closer, ok := resource.(interface{ Close() }); ok {
			closer.Close()
		}
	}
}

func (s *SymonSampler) logSamplingError(err error) {
	if err == nil {
		return
	}
	if monitor.ShouldCaptureSamplingError(err) {
		s.logger.CaptureError(fmt.Errorf("symon: sampling error: %v", err))
		return
	}
	s.logger.Debug(fmt.Sprintf("symon: benign sampling error: %v", err))
}

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
