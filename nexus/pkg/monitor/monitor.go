package monitor

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"time"

	"github.com/wandb/wandb/nexus/pkg/observability"
	"github.com/wandb/wandb/nexus/pkg/service"
	"google.golang.org/protobuf/types/known/timestamppb"
)

const BufferSize = 32

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

func makeStatsRecord(stats map[string]float64) *service.Record {
	record := &service.Record{
		RecordType: &service.Record_Stats{
			Stats: &service.StatsRecord{
				StatsType: service.StatsRecord_SYSTEM,
				Timestamp: timestamppb.Now(),
			},
		},
		Control: &service.Control{AlwaysSend: true},
	}

	for k, v := range stats {
		jsonData, err := json.Marshal(v)
		if err != nil {
			continue
		}
		record.GetStats().Item = append(record.GetStats().Item, &service.StatsItem{
			Key:       k,
			ValueJson: string(jsonData),
		})
	}

	return record
}

type Asset interface {
	Name() string
	SampleMetrics()
	AggregateMetrics() map[string]float64
	ClearMetrics()
	IsAvailable() bool
	Probe() map[string]map[string]interface{}
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
	OutChan chan *service.Record

	// settings is the settings for the system monitor
	settings *service.Settings

	// logger is the logger for the system monitor
	logger *observability.NexusLogger
}

// NewSystemMonitor creates a new SystemMonitor with the given settings
func NewSystemMonitor(
	settings *service.Settings,
	logger *observability.NexusLogger,
) *SystemMonitor {
	ctx, cancel := context.WithCancel(context.Background())

	systemMonitor := &SystemMonitor{
		ctx:      ctx,
		cancel:   cancel,
		wg:       sync.WaitGroup{},
		OutChan:  make(chan *service.Record, BufferSize),
		settings: settings,
		logger:   logger,
	}

	// if stats are disabled, return early
	if settings.XDisableStats.GetValue() {
		return systemMonitor
	}

	assets := []Asset{
		NewMemory(settings),
		NewCPU(settings),
		NewDisk(settings),
		NewNetwork(settings),
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
	// if stats are disabled, do nothing
	if sm.settings.XDisableStats.GetValue() {
		return
	}

	sm.logger.Info("Starting system monitor")
	// start monitoring the assets
	for _, asset := range sm.assets {
		sm.wg.Add(1)
		go sm.Monitor(asset)
	}
}

func (sm *SystemMonitor) Monitor(asset Asset) {

	// recover from panic and log the error
	defer func() {
		sm.wg.Done()
		if err := recover(); err != nil {
			e := fmt.Errorf("%v", err)
			sm.logger.CaptureError("monitor: panic", e)
		}
	}()

	// todo: rename the setting...should be SamplingIntervalSeconds
	samplingInterval := time.Duration(sm.settings.XStatsSampleRateSeconds.GetValue() * float64(time.Second))
	samplesToAverage := sm.settings.XStatsSamplesToAverage.GetValue()
	sm.logger.Debug(
		fmt.Sprintf(
			"samplingInterval: %v, samplesToAverage: %v",
			samplingInterval,
			samplesToAverage,
		),
	)

	// Create a ticker that fires every `samplingInterval` seconds
	ticker := time.NewTicker(samplingInterval)
	defer ticker.Stop()

	// Create a new channel and immediately send a signal to it.
	// This is to ensure that the first sample is taken immediately.
	tickChan := make(chan time.Time, 1)
	tickChan <- time.Now()

	// Forward signals from the ticker to tickChan
	go func() {
		for t := range ticker.C {
			tickChan <- t
		}
	}()

	samplesCollected := int32(0)

	for {
		select {
		case <-sm.ctx.Done():
			return
		case <-tickChan:
			asset.SampleMetrics()
			samplesCollected++

			if samplesCollected == samplesToAverage {
				aggregatedMetrics := asset.AggregateMetrics()
				if len(aggregatedMetrics) > 0 {
					// publish metrics
					record := makeStatsRecord(aggregatedMetrics)
					// ensure that the context is not done before sending the record
					select {
					case <-sm.ctx.Done():
						return
					default:
						sm.OutChan <- record
					}
					asset.ClearMetrics()
				}

				// reset samplesCollected
				samplesCollected = int32(0)
			}
		}
	}

}

func (sm *SystemMonitor) Stop() {
	sm.logger.Info("Stopping system monitor")
	sm.cancel()
	sm.wg.Wait()
	close(sm.OutChan)
	sm.logger.Info("Stopped system monitor")
}
