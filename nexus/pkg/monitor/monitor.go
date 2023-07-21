package monitor

import (
	"encoding/json"
	"fmt"
	"sync"
	"time"

	"github.com/wandb/wandb/nexus/pkg/observability"
	"github.com/wandb/wandb/nexus/pkg/service"
	"google.golang.org/protobuf/types/known/timestamppb"
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
	// wg is the wait group for the system monitor
	wg sync.WaitGroup

	// assets is the list of assets to monitor
	assets []Asset

	//	outChan is the channel for outgoing messages
	OutChan chan<- *service.Record

	// settings is the settings for the system monitor
	settings *service.Settings

	// logger is the logger for the system monitor
	logger *observability.NexusLogger
}

// NewSystemMonitor creates a new SystemMonitor with the given settings
func NewSystemMonitor(
	outChan chan<- *service.Record,
	settings *service.Settings,
	logger *observability.NexusLogger,
) *SystemMonitor {

	systemMonitor := &SystemMonitor{
		wg:       sync.WaitGroup{},
		OutChan:  outChan,
		settings: settings,
		logger:   logger,
	}

	assets := []Asset{
		NewMemory(),
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
			sm.logger.Debug("panic in system monitor", err)
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

	for range tickChan {
		asset.SampleMetrics()
		samplesCollected++

		if samplesCollected == samplesToAverage {
			aggregatedMetrics := asset.AggregateMetrics()
			if len(aggregatedMetrics) > 0 {
				// publish metrics
				record := makeStatsRecord(aggregatedMetrics)
				sm.OutChan <- record

				asset.ClearMetrics()
			}

			// reset samplesCollected
			samplesCollected = int32(0)
		}
	}

}

func (sm *SystemMonitor) Stop() {
	sm.logger.Info("Stopping system monitor")
	close(sm.OutChan)
	sm.wg.Wait()
	sm.logger.Info("Stopped system monitor")
}
