package monitor

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"sync"
	"time"

	"golang.org/x/time/rate"

	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/types/known/timestamppb"
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

func makeStatsRecord(stats map[string]float64, timeStamp *timestamppb.Timestamp) *service.Record {
	statsItems := make([]*service.StatsItem, 0, len(stats))
	for k, v := range stats {
		jsonData, err := json.Marshal(v)
		if err != nil {
			continue
		}
		statsItems = append(statsItems, &service.StatsItem{
			Key:       k,
			ValueJson: string(jsonData),
		})
	}

	return &service.Record{
		RecordType: &service.Record_Stats{
			Stats: &service.StatsRecord{
				StatsType: service.StatsRecord_SYSTEM,
				Timestamp: timeStamp,
				Item:      statsItems,
			},
		},
		Control: &service.Control{AlwaysSend: true},
	}
}

type Asset interface {
	Name() string
	SampleMetrics()
	AggregateMetrics() map[string]float64
	ClearMetrics()
	IsAvailable() bool
	Probe() *service.MetadataRequest
}

type SystemMonitor struct {
	// ctx is the context for the system monitor
	ctx    context.Context
	cancel context.CancelFunc

	// wg is the wait group for the system monitor
	wg sync.WaitGroup

	// assets is the list of assets to monitor
	assets []Asset

	//	outChan is the channel for outgoing messages
	outChan chan *service.Record

	// Buffer is the metrics buffer for the system monitor
	buffer *Buffer

	// settings is the settings for the system monitor
	settings *settings.Settings

	// samplingInterval is the interval at which metrics are sampled
	samplingInterval time.Duration

	// samplesToAverage is the number of samples to average before sending the metrics
	samplesToAverage int

	// logger is the logger for the system monitor
	logger *observability.CoreLogger
}

// NewSystemMonitor creates a new SystemMonitor with the given settings
func NewSystemMonitor(
	logger *observability.CoreLogger,
	settings *settings.Settings,
	outChan chan *service.Record,
) *SystemMonitor {
	sbs := settings.GetXStatsBufferSize()
	var buffer *Buffer
	// if buffer size is 0, don't create a buffer
	// a positive buffer size restricts the number of metrics that are kept in memory
	// value of -1 indicates that all sampled metrics will be kept in memory
	if sbs != 0 {
		buffer = NewBuffer(sbs)
	}

	systemMonitor := &SystemMonitor{
		wg:               sync.WaitGroup{},
		settings:         settings,
		logger:           logger,
		outChan:          outChan,
		buffer:           buffer,
		samplingInterval: defaultSamplingInterval,
		samplesToAverage: defaultSamplesToAverage,
	}

	// TODO: rename the setting...should be SamplingIntervalSeconds
	if si := settings.GetXStatsSampleRateSeconds(); si != 0 {
		systemMonitor.samplingInterval = time.Duration(si * float64(time.Second))
	}
	if sta := settings.GetXStatsSamplesToAverage(); sta != 0 {
		systemMonitor.samplesToAverage = int(sta)
	}

	systemMonitor.logger.Debug(
		fmt.Sprintf(
			"samplingInterval: %v, samplesToAverage: %v",
			systemMonitor.samplingInterval,
			systemMonitor.samplesToAverage,
		),
	)

	// if stats are disabled, return early
	if settings.GetXDisableStats() {
		return systemMonitor
	}

	assets := []Asset{
		NewMemory(settings),
		NewCPU(settings),
		NewDisk(settings),
		NewNetwork(),
		NewGPUNvidia(settings),
		NewGPUAMD(),
		NewGPUApple(),
	}

	// if asset is available, add it to the list of assets to monitor
	for _, asset := range assets {
		if asset.IsAvailable() {
			systemMonitor.assets = append(systemMonitor.assets, asset)
		}
	}

	return systemMonitor
}

func (sm *SystemMonitor) Do() {
	if sm == nil {
		return
	}
	// reset context:
	sm.ctx, sm.cancel = context.WithCancel(context.Background())

	sm.logger.Info("Starting system monitor")
	// start monitoring the assets
	for _, asset := range sm.assets {
		sm.wg.Add(1)
		go sm.Monitor(asset)
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

func (sm *SystemMonitor) Probe() *service.MetadataRequest {
	if sm == nil {
		return nil
	}
	systemInfo := service.MetadataRequest{}
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

func (sm *SystemMonitor) Monitor(asset Asset) {
	// recover from panic and log the error
	defer func() {
		sm.wg.Done()
		if err := recover(); err != nil {
			sm.logger.CaptureError(fmt.Errorf("monitor: panic: %v", err))
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
			asset.SampleMetrics()

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
				select {
				case <-sm.ctx.Done():
					return
				case sm.outChan <- makeStatsRecord(aggregatedMetrics, ts):
				}
			})
		}
	}

}

func (sm *SystemMonitor) GetBuffer() map[string]List {
	if sm == nil || sm.buffer == nil {
		return nil
	}
	sm.buffer.mutex.Lock()
	defer sm.buffer.mutex.Unlock()
	return sm.buffer.elements
}

func (sm *SystemMonitor) Stop() {
	if sm == nil || sm.cancel == nil {
		return
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
