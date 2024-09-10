package monitor

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"sync/atomic"
	"time"

	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/pkg/observability"
	"google.golang.org/protobuf/types/known/timestamppb"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	defaultSamplingInterval = 10.0 * time.Second
)

func makeStatsRecord(stats map[string]any, timeStamp *timestamppb.Timestamp) *spb.Record {
	statsItems := make([]*spb.StatsItem, 0, len(stats))
	for k, v := range stats {
		jsonData, err := json.Marshal(v)
		if err != nil {
			continue
		}
		statsItems = append(statsItems, &spb.StatsItem{
			Key:       k,
			ValueJson: string(jsonData),
		})
	}

	return &spb.Record{
		RecordType: &spb.Record_Stats{
			Stats: &spb.StatsRecord{
				StatsType: spb.StatsRecord_SYSTEM,
				Timestamp: timeStamp,
				Item:      statsItems,
			},
		},
		Control: &spb.Control{AlwaysSend: true},
	}
}

func makeMetadataRecord(metadata *spb.MetadataRequest) *spb.Record {
	return &spb.Record{
		RecordType: &spb.Record_Request{
			Request: &spb.Request{
				RequestType: &spb.Request_Metadata{
					Metadata: metadata,
				},
			},
		},
	}
}

type Asset interface {
	Name() string
	Sample() (map[string]any, error)
	IsAvailable() bool
	Probe() *spb.MetadataRequest
}

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
	settings *spb.Settings

	// The interval at which metrics are sampled
	samplingInterval time.Duration

	// A logger for internal debug logging.
	logger *observability.CoreLogger
}

func New(
	logger *observability.CoreLogger,
	settings *spb.Settings,
	extraWork runwork.ExtraWork,
) *SystemMonitor {
	sbs := settings.XStatsBufferSize.GetValue()
	var buffer *Buffer
	// if buffer size is 0, don't create a buffer.
	// a positive buffer size limits the number of metrics that are kept in memory.
	// a value of -1 indicates that all sampled metrics will be kept in memory.
	if sbs != 0 {
		buffer = NewBuffer(sbs)
	}

	ctx, cancel := context.WithCancel(context.Background())
	systemMonitor := &SystemMonitor{
		ctx:              ctx,
		cancel:           cancel,
		wg:               sync.WaitGroup{},
		settings:         settings,
		logger:           logger,
		extraWork:        extraWork,
		buffer:           buffer,
		samplingInterval: defaultSamplingInterval,
	}

	// TODO: rename the setting...should be SamplingIntervalSeconds
	if si := settings.XStatsSamplingInterval; si != nil {
		systemMonitor.samplingInterval = time.Duration(si.GetValue() * float64(time.Second))
	}

	systemMonitor.logger.Debug(
		fmt.Sprintf(
			"monitor: sampling interval: %v",
			systemMonitor.samplingInterval,
		),
	)

	// if stats are disabled, return early
	if settings.XDisableStats.GetValue() {
		return systemMonitor
	}

	pid := settings.XStatsPid.GetValue()
	diskPaths := settings.XStatsDiskPaths.GetValue()
	samplingInterval := settings.XStatsSamplingInterval.GetValue()
	neuronMonitorConfigPath := settings.XStatsNeuronMonitorConfigPath.GetValue()

	// assets to be monitored.
	if cpu := NewCPU(pid); cpu != nil {
		systemMonitor.assets = append(systemMonitor.assets, cpu)
	}
	if disk := NewDisk(diskPaths); disk != nil {
		systemMonitor.assets = append(systemMonitor.assets, disk)
	}
	if memory := NewMemory(pid); memory != nil {
		systemMonitor.assets = append(systemMonitor.assets, memory)
	}
	if network := NewNetwork(); network != nil {
		systemMonitor.assets = append(systemMonitor.assets, network)
	}
	if gpu := NewGPUNvidia(logger, pid, samplingInterval); gpu != nil {
		systemMonitor.assets = append(systemMonitor.assets, gpu)
	}
	if gpu := NewGPUAMD(logger); gpu != nil {
		systemMonitor.assets = append(systemMonitor.assets, gpu)
	}
	if gpu := NewGPUApple(); gpu != nil {
		systemMonitor.assets = append(systemMonitor.assets, gpu)
	}
	if slurm := NewSLURM(); slurm != nil {
		systemMonitor.assets = append(systemMonitor.assets, slurm)
	}
	if trainium := NewTrainium(logger, pid, samplingInterval, neuronMonitorConfigPath); trainium != nil {
		systemMonitor.assets = append(systemMonitor.assets, trainium)
	}

	// OpenMetrics endpoints to monitor.
	if endpoints := settings.XStatsOpenMetricsEndpoints.GetValue(); endpoints != nil {
		for name, url := range endpoints {
			filters := settings.XStatsOpenMetricsFilters
			if om := NewOpenMetrics(logger, name, url, filters, nil); om != nil {
				systemMonitor.assets = append(systemMonitor.assets, om)
			}
		}
	}

	return systemMonitor
}

// GetState returns the current state of the SystemMonitor.
func (sm *SystemMonitor) GetState() int32 {
	return sm.state.Load()
}

// probe gathers system information from all assets.
func (sm *SystemMonitor) probe() *spb.MetadataRequest {
	systemInfo := spb.MetadataRequest{}
	for _, asset := range sm.assets {
		probeResponse := asset.Probe()
		if probeResponse != nil {
			proto.Merge(&systemInfo, probeResponse)
		}
	}
	return &systemInfo
}

const (
	StateStopped int32 = iota
	StateRunning
	StatePaused
)

// Start begins the monitoring process for all assets and probes the system information.
//
// Only a stopped monitor can be started. It's safe to call multiple times.
func (sm *SystemMonitor) Start() {
	if sm == nil {
		return
	}

	if !sm.state.CompareAndSwap(StateStopped, StateRunning) {
		return // Already started or paused
	}

	sm.logger.Info("Starting system monitor")
	// start monitoring the assets
	for _, asset := range sm.assets {
		sm.wg.Add(1)
		go sm.Monitor(asset)
	}

	// probe the asset information
	go func() {
		systemInfo := sm.probe()
		if systemInfo != nil {
			sm.extraWork.AddWorkOrCancel(
				sm.ctx.Done(),
				runwork.WorkFromRecord(
					makeMetadataRecord(systemInfo),
				),
			)
		}
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

// Monitor starts the monitoring process for a single asset.
//
// It handles sampling, aggregation, and reporting of metrics
// and is meant to run in its own goroutine.
func (sm *SystemMonitor) Monitor(asset Asset) {
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

			// NOTE: the pattern in Sample is to capture whatever metrics are available,
			// accumulate errors along the way, and log them here.
			metrics, err := asset.Sample()
			if err != nil {
				sm.logger.CaptureError(
					fmt.Errorf("monitor: %v: error sampling metrics: %v", asset.Name(), err),
				)
			}

			if len(metrics) == 0 {
				continue // nothing to do
			}
			ts := timestamppb.Now()
			// Also store aggregated metrics in the buffer if we have one
			if sm.buffer != nil {
				for k, v := range metrics {
					if v, ok := v.(float64); ok {
						sm.buffer.push(k, ts, v)
					}
				}
			}

			// publish metrics
			sm.extraWork.AddWorkOrCancel(
				sm.ctx.Done(),
				runwork.WorkFromRecord(
					makeStatsRecord(metrics, ts),
				),
			)
		}
	}

}

// GetBuffer returns the current buffer of collected metrics.
func (sm *SystemMonitor) GetBuffer() map[string]List {
	if sm == nil || sm.buffer == nil {
		return nil
	}
	sm.buffer.mutex.Lock()
	defer sm.buffer.mutex.Unlock()
	return sm.buffer.elements
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
