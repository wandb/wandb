package monitor

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"
	"time"

	"google.golang.org/protobuf/proto"

	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"google.golang.org/protobuf/types/known/timestamppb"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	defaultSamplingInterval = 10.0 * time.Second
)

// State definitions for the SystemMonitor.
const (
	StateStopped int32 = iota
	StateRunning
	StatePaused
)

// Asset defines the interface for system assets to be monitored.
type Asset interface {
	Name() string
	Sample() (*spb.StatsRecord, error)
	IsAvailable() bool
	Probe() *spb.MetadataRequest
}

// SystemMonitor is responsible for monitoring system metrics across various assets.
type SystemMonitor struct {
	// The context for the system monitor
	ctx    context.Context
	cancel context.CancelFunc

	// The wait group for the system monitor
	wg sync.WaitGroup

	// The state of the system monitor: stopped, running, or paused
	state atomic.Int32

	// The list of assets to monitor
	assets []Asset

	// extraWork accepts outgoing messages for the run
	extraWork runwork.ExtraWork

	// The metrics buffer for the system monitor
	buffer *Buffer

	// settings is the settings for the system monitor
	settings *settings.Settings

	// The interval at which metrics are sampled
	samplingInterval time.Duration

	// A logger for internal debug logging.
	logger *observability.CoreLogger
}

// NewSystemMonitor initializes and returns a new SystemMonitor instance.
//
// It sets up assets based on provided settings and configures the metrics buffer.
func NewSystemMonitor(
	logger *observability.CoreLogger,
	settings *settings.Settings,
	extraWork runwork.ExtraWork,
) *SystemMonitor {
	ctx, cancel := context.WithCancel(context.Background())
	sm := &SystemMonitor{
		ctx:              ctx,
		cancel:           cancel,
		wg:               sync.WaitGroup{},
		settings:         settings,
		logger:           logger,
		extraWork:        extraWork,
		samplingInterval: defaultSamplingInterval,
	}

	bufferSize := settings.GetStatsBufferSize()
	// Initialize the buffer if a buffer size is provided.
	// A positive buffer size N indicates that only the last N samples will be kept in memory.
	// A value of -1 indicates that all sampled metrics will be kept in memory.
	if bufferSize != 0 {
		sm.buffer = NewBuffer(bufferSize)
	}

	if si := settings.GetStatsSamplingInterval(); si != 0 {
		sm.samplingInterval = time.Duration(si * float64(time.Second))
	}
	sm.logger.Debug(fmt.Sprintf("monitor: sampling interval: %v", sm.samplingInterval))

	// Early return if stats collection is disabled
	if settings.IsDisableStats() {
		return sm
	}

	// Initialize the assets to monitor
	sm.InitializeAssets(settings)

	return sm
}

// initializeAssets sets up the assets to be monitored based on the provided settings.
func (sm *SystemMonitor) InitializeAssets(settings *settings.Settings) {
	pid := settings.GetStatsPid()
	diskPaths := settings.GetStatsDiskPaths()
	samplingInterval := settings.GetStatsSamplingInterval()
	neuronMonitorConfigPath := settings.GetStatsNeuronMonitorConfigPath()
	gpuDeviceIds := settings.GetStatsGpuDeviceIds()

	// assets to be monitored.
	if cpu := NewCPU(pid); cpu != nil {
		sm.assets = append(sm.assets, cpu)
	}
	if disk := NewDisk(diskPaths); disk != nil {
		sm.assets = append(sm.assets, disk)
	}
	if memory := NewMemory(pid); memory != nil {
		sm.assets = append(sm.assets, memory)
	}
	if network := NewNetwork(); network != nil {
		sm.assets = append(sm.assets, network)
	}
	if gpu := NewGPU(pid, gpuDeviceIds); gpu != nil {
		sm.assets = append(sm.assets, gpu)
	}
	if gpu := NewGPUAMD(sm.logger); gpu != nil {
		sm.assets = append(sm.assets, gpu)
	}
	if tpu := NewTPU(); tpu != nil {
		sm.assets = append(sm.assets, tpu)
	}
	if slurm := NewSLURM(); slurm != nil {
		sm.assets = append(sm.assets, slurm)
	}
	if trainium := NewTrainium(sm.logger, pid, samplingInterval, neuronMonitorConfigPath); trainium != nil {
		sm.assets = append(sm.assets, trainium)
	}

	// OpenMetrics endpoints to monitor.
	if endpoints := settings.GetStatsOpenMetricsEndpoints(); endpoints != nil {
		for name, url := range endpoints {
			filters := settings.GetStatsOpenMetricsFilters()
			headers := settings.GetStatsOpenMetricsHeaders()
			if om := NewOpenMetrics(sm.logger, name, url, filters, headers, nil); om != nil {
				sm.assets = append(sm.assets, om)
			}
		}
	}
}

// marshal constructs a StatsRecord protobuf message from the provided stats map and timestamp.
func marshal(
	stats map[string]any,
	timeStamp *timestamppb.Timestamp,
) *spb.StatsRecord {
	statsItems := make([]*spb.StatsItem, 0, len(stats))
	for k, v := range stats {
		jsonData, err := simplejsonext.Marshal(v)
		if err != nil {
			continue
		}
		key := k
		statsItems = append(statsItems, &spb.StatsItem{
			Key:       key,
			ValueJson: string(jsonData),
		})
	}

	return &spb.StatsRecord{
		StatsType: spb.StatsRecord_SYSTEM,
		Timestamp: timeStamp,
		Item:      statsItems,
	}
}

// GetState returns the current state of the SystemMonitor.
func (sm *SystemMonitor) GetState() int32 {
	return sm.state.Load()
}

// probe gathers system information from all assets and merges their metadata.
func (sm *SystemMonitor) probe() *spb.Record {
	defer func() {
		if err := recover(); err != nil {
			sm.logger.CaptureError(
				fmt.Errorf("monitor: panic: %v", err),
			)
		}
	}()

	systemInfo := spb.MetadataRequest{}
	for _, asset := range sm.assets {
		probeResponse := asset.Probe()
		if probeResponse != nil {
			proto.Merge(&systemInfo, probeResponse)
		}
	}

	return &spb.Record{
		RecordType: &spb.Record_Request{
			Request: &spb.Request{
				RequestType: &spb.Request_Metadata{
					Metadata: &systemInfo,
				},
			},
		},
	}
}

// Start begins the monitoring process for all assets and probes system information.
//
// It is safe to call Start multiple times; only a stopped monitor will initiate.
func (sm *SystemMonitor) Start() {
	if sm == nil {
		return
	}

	if !sm.state.CompareAndSwap(StateStopped, StateRunning) {
		return // Already started or paused
	}

	sm.logger.Info("Starting system monitor")
	// Start collecting metrics for all assets.
	for _, asset := range sm.assets {
		sm.wg.Add(1)
		go sm.monitorAsset(asset)
	}

	// Probe the asset information.
	go func() {
		sm.extraWork.AddWorkOrCancel(
			sm.ctx.Done(),
			runwork.WorkFromRecord(
				sm.probe(),
			),
		)
	}()
}

// Pause temporarily stops the monitoring process.
//
// Monitoring can be resumed later with the Resume method.
//
// Pause and Resume are used in notebook environments to ensure that
// metrics are only collected when a cell is running. We do it this way
// to prevent the overhead of starting and stopping the monitor for each cell.
func (sm *SystemMonitor) Pause() {
	if sm.state.CompareAndSwap(StateRunning, StatePaused) {
		sm.logger.Info("Pausing system monitor")
	}
}

// Resume restarts the monitoring process after it has been paused.
func (sm *SystemMonitor) Resume() {
	if sm.state.CompareAndSwap(StatePaused, StateRunning) {
		sm.logger.Info("Resuming system monitor")
	}
}

// monitorAsset handles the monitoring loop for a single asset.
//
// It handles sampling, aggregation, and reporting of metrics
// and is meant to run in its own goroutine.
func (sm *SystemMonitor) monitorAsset(asset Asset) {
	if asset == nil || !asset.IsAvailable() {
		sm.wg.Done()
		return
	}

	// recover from panic and log the error
	defer func() {
		sm.wg.Done()
		if err := recover(); err != nil {
			if asset != nil {
				sm.logger.CaptureError(
					fmt.Errorf("monitor: panic: %v", err),
					"asset_name", asset.Name())
			}
		}
	}()

	// Create a ticker that fires every `samplingInterval` seconds
	ticker := time.NewTicker(sm.samplingInterval)
	defer ticker.Stop()

	for {
		select {
		case <-sm.ctx.Done():
			return
		case <-ticker.C:
			if sm.state.Load() != StateRunning {
				continue // Skip work when not running
			}

			metrics, err := asset.Sample()
			if err != nil {
				sm.logger.CaptureError(
					fmt.Errorf("monitor: %v: error sampling metrics: %v", asset.Name(), err),
				)
				// shutdown the asset to be on the safe side
				if closer, ok := asset.(interface{ Close() }); ok {
					closer.Close()
				}
				return
			}

			if metrics == nil || len(metrics.Item) == 0 {
				continue // nothing to do
			}

			// Push metrics to the buffer
			sm.buffer.Push(metrics)

			// Label for custom grouping of stats, e.g. per node in a multi-node run.
			if label := sm.settings.GetLabel(); label != "" {
				for _, item := range metrics.Item {
					item.Key = fmt.Sprintf("%s/l:%s", item.Key, label)
				}
			}

			// publish metrics
			record := &spb.Record{
				RecordType: &spb.Record_Stats{
					Stats: metrics,
				},
				Control: &spb.Control{AlwaysSend: true},
			}
			sm.extraWork.AddWorkOrCancel(
				sm.ctx.Done(),
				runwork.WorkFromRecord(record),
			)
		}
	}

}

// GetBuffer returns the current buffer of collected metrics.
//
// The buffer is a map of metric names to a slice of measurements - a list of
// (timestamp, value) pairs.
func (sm *SystemMonitor) GetBuffer() map[string][]Measurement {
	if sm == nil || sm.buffer == nil {
		return nil
	}
	return sm.buffer.GetMeasurements()
}

// Finish stops the monitoring process and performs necessary cleanup.
//
// NOTE: asset.Close is a potentially expensive operation.
func (sm *SystemMonitor) Finish() {
	if sm == nil || sm.cancel == nil {
		return
	}
	if sm.state.Swap(StateStopped) == StateStopped {
		return // Already stopped
	}

	sm.logger.Info("Stopping system monitor")

	// signal to stop monitoring the assets
	sm.cancel()
	// wait for all assets to stop monitoring
	sm.wg.Wait()
	// close the assets, if they require any cleanup
	for _, asset := range sm.assets {
		if closer, ok := asset.(interface{ Close() }); ok {
			closer.Close()
		}
	}
	sm.logger.Info("Stopped system monitor")
}
