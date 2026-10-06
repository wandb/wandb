package leet

import (
	"context"
	"fmt"
	"maps"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"

	"golang.org/x/sync/errgroup"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// SymonProbeMsg carries the host facts that do not change while symon runs.
type SymonProbeMsg struct {
	Env      *spb.EnvironmentRecord
	CPUModel string
}

// SymonSampleMsg is one sampling pass: the system metrics and the processes.
type SymonSampleMsg struct {
	StatsMsg
	Processes []monitor.ProcessStat
}

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
// system and accelerator resources. The resulting metrics are aligned to a single
// wall-clock timestamp before they are merged into one StatsMsg for the UI.
type SymonSampler struct {
	interval  time.Duration
	resources []monitor.Resource
	processes *monitor.Processes
	logger    *observability.CoreLogger

	// prev and prevAt are the previous sample's metrics and time, from
	// which the next sample's I/O rates are derived.
	prev   map[string]float64
	prevAt time.Time
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
		interval:  interval,
		processes: monitor.NewProcesses(),
		logger:    logger,
	}

	sampler.resources = append(sampler.resources,
		monitor.NewSystem(monitor.SystemParams{
			Pid:                         0,
			TrackProcessTree:            false,
			DiskPaths:                   defaultSymonDiskPaths(),
			DisableCgroupResourceLimits: true,
		}),
		monitor.NewCPU(),
		monitor.NewHost(),
		monitor.NewXPU(context.Background(), monitor.NewXPUResourceManager(false), 0, nil),
	)

	return sampler
}

// Interval reports the configured delay between sampling passes.
func (s *SymonSampler) Interval() time.Duration {
	return s.interval
}

// Sample gathers one aligned snapshot across all resources and the
// process table.
func (s *SymonSampler) Sample() SymonSampleMsg {
	now := time.Now()
	out := SymonSampleMsg{StatsMsg: StatsMsg{
		Timestamp: now.Unix(),
		Metrics:   make(map[string]float64),
	}}

	var mu sync.Mutex
	var g errgroup.Group

	g.Go(func() error {
		defer s.recoverSamplingPanic()

		procs, err := s.processes.Sample()
		if err != nil {
			s.logSamplingError(err)
			return nil
		}
		out.Processes = procs
		return nil
	})

	for _, resource := range s.resources {
		g.Go(func() error {
			defer s.recoverSamplingPanic()

			record, err := resource.Sample()
			if err != nil {
				s.logSamplingError(err)
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

	metrics := out.Metrics
	counters := maps.Clone(metrics)
	deriveRates(s.prev, metrics, now.Sub(s.prevAt))
	s.prev, s.prevAt = counters, now

	// Disk usage is charted as a percentage and memory as used, so the
	// flat used-bytes and available-memory lines only take up cells.
	for key := range metrics {
		if strings.HasSuffix(key, ".usageGB") || key == "proc.memory.availableMB" {
			delete(metrics, key)
		}
	}
	return out
}

// recoverSamplingPanic logs a panic in a sampling goroutine. Hardware
// sampling paths are known to panic (see SystemMonitor), and a panic here
// would crash the whole TUI: bubbletea's panic recovery does not cover
// goroutines spawned by commands.
func (s *SymonSampler) recoverSamplingPanic() {
	if r := recover(); r != nil {
		s.logger.CaptureError(
			"leet",
			fmt.Errorf("symon: panic sampling resource: %v", r),
		)
	}
}

// deriveRates replaces the cumulative network and disk I/O counters in cur
// with bytes-per-second rates over the elapsed time since prev. The
// counters are dropped even when prev lacks them, so the grid never charts
// totals since the monitor started.
func deriveRates(prev, cur map[string]float64, elapsed time.Duration) {
	for key, value := range cur {
		rateKey, scale, ok := ioRateKey(key)
		if !ok {
			continue
		}
		delete(cur, key)
		before, ok := prev[key]
		if !ok || elapsed <= 0 || value < before {
			continue
		}
		cur[rateKey] = (value - before) * scale / elapsed.Seconds()
	}
}

// ioRateKey maps a cumulative I/O counter to its rate key and the factor
// that converts the counter's unit to bytes: monitor.System reports the
// network counters in bytes and the disk counters in MiB.
func ioRateKey(key string) (string, float64, bool) {
	switch key {
	case "network.recv":
		return "network.recvBps", 1, true
	case "network.sent":
		return "network.sentBps", 1, true
	}
	const mib = 1024 * 1024
	if dev, ok := strings.CutPrefix(key, "disk."); ok {
		if dev, ok := strings.CutSuffix(dev, ".in"); ok {
			return "disk." + dev + ".readBps", mib, true
		}
		if dev, ok := strings.CutSuffix(dev, ".out"); ok {
			return "disk." + dev + ".writeBps", mib, true
		}
	}
	return "", 0, false
}

// Probe gathers the host facts from every resource. Starting the wandb-xpu
// sidecar can take seconds, so call it from a command, not from Update.
func (s *SymonSampler) Probe(ctx context.Context) SymonProbeMsg {
	defer s.recoverSamplingPanic()

	msg := SymonProbeMsg{Env: &spb.EnvironmentRecord{}, CPUModel: monitor.CPUModel()}
	for _, resource := range s.resources {
		if rec := resource.Probe(ctx); rec != nil {
			proto.Merge(msg.Env, rec)
		}
	}
	return msg
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
