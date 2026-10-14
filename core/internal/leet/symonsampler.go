package leet

import (
	"context"
	"maps"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync/atomic"
	"time"

	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/sharedmode"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// SymonProbeMsg carries the host facts that do not change while symon runs.
type SymonProbeMsg struct {
	Env *spb.EnvironmentRecord
}

// SymonSampleMsg is one sampling pass: the system metrics and the processes.
type SymonSampleMsg struct {
	StatsMsg
	Processes []*spb.ProcessStats
}

// DefaultSymonSamplingInterval is the sampling cadence used by SYMON when the
// caller does not provide an explicit interval.
const DefaultSymonSamplingInterval = 2 * time.Second

// SymonSamplerParams configures a SymonSampler.
type SymonSamplerParams struct {
	// Interval controls the delay between successive sampling passes. Values
	// less than or equal to zero use DefaultSymonSamplingInterval.
	Interval time.Duration

	// Logger receives the sidecar's debug messages and errors.
	Logger *observability.CoreLogger
}

// SymonSampler produces live StatsMsg updates from the wandb-xpu sidecar.
//
// The sidecar streams the system metrics and the process table at the
// sampling interval. Each call to Sample returns the latest of them with
// the I/O counters replaced by rates.
type SymonSampler struct {
	interval time.Duration
	xpu      *monitor.XPU

	// subscription describes what the sampler subscribes to.
	subscription *spb.SubscribeRequest

	// latest is the sidecar's most recent sample.
	latest atomic.Pointer[SymonSampleMsg]

	// prev and prevAt are the previous sidecar sample's metrics and time,
	// from which the next sample's I/O rates are derived.
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

	return &SymonSampler{
		interval: interval,
		xpu: monitor.NewXPU(
			context.Background(),
			monitor.NewXPUResourceManager(false),
			logger,
		),
		subscription: &spb.SubscribeRequest{
			IntervalSeconds: interval.Seconds(),
			SubscriberId:    string(sharedmode.RandomClientID()),
			DiskPaths:       defaultSymonDiskPaths(),
			DisableCgroup:   true,
			HostDetails:     true,
		},
	}
}

// Interval reports the configured delay between sampling passes.
func (s *SymonSampler) Interval() time.Duration {
	return s.interval
}

// Sample returns the sidecar's latest sample stamped with the current time.
//
// The first call starts the sidecar, whose samples arrive from the next
// call on.
func (s *SymonSampler) Sample() SymonSampleMsg {
	s.xpu.Subscribe(s.subscription, s.store)

	msg := SymonSampleMsg{StatsMsg: StatsMsg{Metrics: map[string]float64{}}}
	if latest := s.latest.Load(); latest != nil {
		msg = *latest
	}
	msg.Timestamp = time.Now().Unix()
	return msg
}

// store keeps a sidecar sample for the next Sample call, with its I/O
// rates derived from the sample before it.
func (s *SymonSampler) store(_ context.Context, response *spb.SubscribeResponse) {
	record := response.GetRecord().GetStats()
	msg, ok := ParseStats("", record).(StatsMsg)
	if !ok {
		return
	}
	at := record.GetTimestamp().AsTime()
	counters := maps.Clone(msg.Metrics)
	deriveRates(s.prev, msg.Metrics, at.Sub(s.prevAt))
	s.prev, s.prevAt = counters, at

	// Disk usage is charted as a percentage and memory as used, so the
	// flat used-bytes and available-memory lines only take up cells.
	for key := range msg.Metrics {
		if strings.HasSuffix(key, ".usageGB") || key == "proc.memory.availableMB" {
			delete(msg.Metrics, key)
		}
	}
	s.latest.Store(&SymonSampleMsg{StatsMsg: msg, Processes: response.GetProcesses()})
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
// that converts the counter's unit to bytes: the sidecar reports the
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

// Probe gathers the host facts from the sidecar. Starting it can take
// seconds, so call Probe from a command, not from Update.
func (s *SymonSampler) Probe(ctx context.Context) SymonProbeMsg {
	metadata := &spb.GetMetadataRequest{DiskPaths: s.subscription.GetDiskPaths()}
	return SymonProbeMsg{Env: s.xpu.Probe(ctx, metadata)}
}

// Cleanup ends the sidecar subscription and releases the sidecar process.
func (s *SymonSampler) Cleanup() {
	s.xpu.Close()
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
