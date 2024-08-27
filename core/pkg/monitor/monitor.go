package monitor

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"golang.org/x/time/rate"

	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/pkg/observability"
	"google.golang.org/protobuf/types/known/timestamppb"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	defaultSamplingInterval = 2.0 * time.Second
	defaultSamplesToAverage = 15
)

func Average(nums []float64) float64 {
	if len(nums) == 0 {
		return 0.0
	}
	total := 0.0
	for _, num := range nums {
		total += num
	}
	return total / float64(len(nums))
}

func makeStatsRecord(stats map[string]float64, timeStamp *timestamppb.Timestamp) *spb.Record {
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

func getSlurmEnvVars() map[string]string {
	slurmVars := make(map[string]string)
	for _, envVar := range os.Environ() {
		keyValPair := strings.SplitN(envVar, "=", 2)
		key := keyValPair[0]
		value := keyValPair[1]

		if strings.HasPrefix(key, "SLURM_") {
			suffix := strings.ToLower(strings.TrimPrefix(key, "SLURM_"))
			slurmVars[suffix] = value
		}
	}
	return slurmVars
}

type Asset interface {
	Name() string
	SampleMetrics() error
	AggregateMetrics() map[string]float64
	ClearMetrics()
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

	// The number of samples to average before sending the metrics
	samplesToAverage int

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
		samplesToAverage: defaultSamplesToAverage,
	}

	// TODO: rename the setting...should be SamplingIntervalSeconds
	if si := settings.XStatsSampleRateSeconds; si != nil {
		systemMonitor.samplingInterval = time.Duration(si.GetValue() * float64(time.Second))
	}
	if sta := settings.XStatsSamplesToAverage; sta != nil {
		systemMonitor.samplesToAverage = int(sta.GetValue())
	}

	systemMonitor.logger.Debug(
		fmt.Sprintf(
			"samplingInterval: %v, samplesToAverage: %v",
			systemMonitor.samplingInterval,
			systemMonitor.samplesToAverage,
		),
	)

	// if stats are disabled, return early
	if settings.XDisableStats.GetValue() {
		return systemMonitor
	}

	pid := settings.XStatsPid.GetValue()
	diskPaths := settings.XStatsDiskPaths.GetValue()
	samplingInterval := settings.XStatsSampleRateSeconds.GetValue()

	systemMonitor.SetAssets([]Asset{
		NewCPU(pid),
		NewDisk(diskPaths),
		NewMemory(pid),
		NewNetwork(),
		// NOTE: we pass the logger for more detailed error reporting
		// during the initial rollout of the GPU monitoring with nvidia_gpu_stats
		// TODO: remove the logger once we are confident that it is stable
		NewGPUNvidia(logger, pid, samplingInterval),
		NewGPUAMD(),
		NewGPUApple(),
	})

	return systemMonitor
}

// SetAssets sets the list of assets to be monitored.
func (sm *SystemMonitor) SetAssets(assets []Asset) {
	sm.assets = assets
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
	// capture SLURM-related environment variables
	for k, v := range getSlurmEnvVars() {
		if systemInfo.Slurm == nil {
			systemInfo.Slurm = make(map[string]string)
		}
		systemInfo.Slurm[k] = v
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
			sm.extraWork.AddRecordOrCancel(
				sm.ctx.Done(),
				makeMetadataRecord(systemInfo),
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
// as opposed to stopping and starting the monitor to prevent the overhead of
// starting and stopping the monitor for each cell.
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
	if !asset.IsAvailable() {
		sm.wg.Done()
		return
	}

	// recover from panic and log the error
	defer func() {
		sm.wg.Done()
		if err := recover(); err != nil {
			sm.logger.CaptureError(
				fmt.Errorf("monitor: panic: %v", err),
				"asset_name", asset.Name())
		}
	}()

	// Create a ticker that fires every `samplingInterval` seconds
	ticker := time.NewTicker(sm.samplingInterval)
	defer ticker.Stop()

	sometimes := rate.Sometimes{Every: sm.samplesToAverage}

	for {
		select {
		case <-sm.ctx.Done():
			return
		case <-ticker.C:
			if sm.state.Load() != StateRunning {
				continue // Skip work when not running
			}

			// NOTE: the pattern in SampleMetric is to capture whatever metrics are available,
			// accumulate errors along the way, and log them here.
			err := asset.SampleMetrics()
			if err != nil {
				sm.logger.CaptureError(
					fmt.Errorf("monitor: %v: error sampling metrics: %v", asset.Name(), err),
				)
			}

			sometimes.Do(func() {
				aggregatedMetrics := asset.AggregateMetrics()
				asset.ClearMetrics()

				if len(aggregatedMetrics) == 0 {
					return // nothing to do
				}
				ts := timestamppb.Now()
				// Also store aggregated metrics in the buffer if we have one
				if sm.buffer != nil {
					for k, v := range aggregatedMetrics {
						sm.buffer.push(k, ts, v)
					}
				}

				// publish metrics
				sm.extraWork.AddRecordOrCancel(
					sm.ctx.Done(),
					makeStatsRecord(aggregatedMetrics, ts),
				)
			})
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
