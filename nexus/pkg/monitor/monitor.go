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

type Metric interface {
	Name() string
	Sample()
	Clear()
	Aggregate() float64
}

type Asset interface {
	Name() string
	Metrics() []Metric
	IsAvailable() bool
	Start()
	Stop()
	Probe() map[string]map[string]interface{}
}

type MetricsMonitor struct {
	ctx      context.Context
	cancel   context.CancelFunc
	wg       sync.WaitGroup
	metrics  []Metric
	settings *service.Settings
	logger   *observability.NexusLogger
	outChan  chan<- *service.Record
}

func NewMetricsMonitor(
	metrics []Metric,
	settings *service.Settings,
	logger *observability.NexusLogger,
	outChan chan<- *service.Record,
) *MetricsMonitor {
	ctx, cancel := context.WithCancel(context.Background())

	return &MetricsMonitor{
		ctx:      ctx,
		cancel:   cancel,
		wg:       sync.WaitGroup{},
		metrics:  metrics,
		settings: settings,
		logger:   logger,
		outChan:  outChan,
	}
}

func (mm *MetricsMonitor) makeStatsRecord(stats map[string]float64) *service.Record {
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

func (mm *MetricsMonitor) Monitor() {

	// recover from panic and log the error
	defer func() {
		if err := recover(); err != nil {
			mm.logger.Debug("panic in metrics monitor", err)
		}
	}()

	// todo: rename the setting...should be SamplingIntervalSeconds
	samplingInterval := time.Duration(mm.settings.XStatsSampleRateSeconds.GetValue() * float64(time.Second))
	samplesToAverage := mm.settings.XStatsSamplesToAverage.GetValue()
	mm.logger.Debug(
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
		case <-mm.ctx.Done():
			return
		case <-tickChan:
			for _, metric := range mm.metrics {
				metric.Sample()
			}
			samplesCollected++

			if samplesCollected == samplesToAverage {
				aggregatedMetrics := mm.aggregate()
				if len(aggregatedMetrics) > 0 {
					// publish metrics
					record := mm.makeStatsRecord(aggregatedMetrics)
					mm.outChan <- record

					for _, metric := range mm.metrics {
						metric.Clear()
					}
				}

				// reset samplesCollected
				samplesCollected = int32(0)
			}
		}
	}
}

func (mm *MetricsMonitor) aggregate() map[string]float64 {
	aggregatedMetrics := make(map[string]float64)

	for _, metric := range mm.metrics {
		aggregatedMetrics[metric.Name()] = metric.Aggregate()
	}
	return aggregatedMetrics
}

func (mm *MetricsMonitor) Stop() {
	mm.logger.Info("Stopping asset metrics monitor")
	mm.cancel()
	mm.wg.Wait()
	mm.logger.Info("Stopped asset metrics monitor")
}

type SystemMonitor struct {
	// assets is the list of assets to monitor
	assets []Asset

	//	outChan is the channel for outgoing messages
	OutChan chan<- *service.Record

	// logger is the logger for the system monitor
	logger *observability.NexusLogger

	// settings is the settings for the system monitor
	settings *service.Settings
}

// NewSystemMonitor creates a new SystemMonitor with the given settings
func NewSystemMonitor(
	outChan chan<- *service.Record,
	settings *service.Settings,
	logger *observability.NexusLogger,
) *SystemMonitor {

	systemMonitor := &SystemMonitor{
		OutChan:  outChan,
		logger:   logger,
		settings: settings,
	}

	systemMonitor.assets = []Asset{
		NewMemory(settings, logger, outChan),
	}

	return systemMonitor
}

func (sm *SystemMonitor) Do() {
	sm.logger.Info("Starting system monitor")
	// start monitoring the assets
	for _, asset := range sm.assets {
		asset.Start()
	}

}

func (sm *SystemMonitor) Stop() {
	sm.logger.Info("Stopping system monitor")
	wg := &sync.WaitGroup{}
	close(sm.OutChan)
	for _, asset := range sm.assets {
		wg.Add(1)
		go func(asset Asset) {
			asset.Stop()
			wg.Done()
		}(asset)
	}
	wg.Wait()
	sm.logger.Info("Stopped system monitor")
}
