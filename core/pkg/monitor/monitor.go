package monitor

import (
	"context"
	"fmt"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/segmentio/encoding/json"

	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
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

type Measurement struct {
	// timestamp of the measurement
	Timestamp *timestamppb.Timestamp
	// value of the measurement
	Value float64
}

type List struct {
	// slice of tuples of (timestamp, value)
	elements []Measurement
	maxSize  int32
}

func (l *List) Append(element Measurement) {
	if (l.maxSize > 0) && (len(l.elements) >= int(l.maxSize)) {
		l.elements = l.elements[1:] // Drop the oldest element
	}
	l.elements = append(l.elements, element) // Add the new element
}

func (l *List) GetElements() []Measurement {
	return l.elements
}

// Buffer is the in-memory metrics buffer for the system monitor
type Buffer struct {
	elements map[string]List
	mutex    sync.RWMutex
	maxSize  int32
}

func NewBuffer(maxSize int32) *Buffer {
	return &Buffer{
		elements: make(map[string]List),
		maxSize:  maxSize,
	}
}

func (mb *Buffer) push(metricName string, timeStamp *timestamppb.Timestamp, metricValue float64) {
	mb.mutex.Lock()
	defer mb.mutex.Unlock()
	buf, ok := mb.elements[metricName]
	if !ok {
		mb.elements[metricName] = List{
			maxSize: mb.maxSize,
		}
	}
	buf.Append(Measurement{
		Timestamp: timeStamp,
		Value:     metricValue,
	})
	mb.elements[metricName] = buf
}

func makeStatsRecord(stats map[string]float64, timeStamp *timestamppb.Timestamp) *service.Record {
	record := &service.Record{
		RecordType: &service.Record_Stats{
			Stats: &service.StatsRecord{
				StatsType: service.StatsRecord_SYSTEM,
				Timestamp: timeStamp,
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
	settings *service.Settings

	// logger is the logger for the system monitor
	logger *observability.CoreLogger
}

// NewSystemMonitor creates a new SystemMonitor with the given settings
func NewSystemMonitor(
	logger *observability.CoreLogger,
	settings *service.Settings,
	outChan chan *service.Record,
) *SystemMonitor {
	sbs := settings.XStatsBufferSize.GetValue()
	var buffer *Buffer
	// if buffer size is 0, don't create a buffer
	// a positive buffer size restricts the number of metrics that are kept in memory
	// value of -1 indicates that all sampled metrics will be kept in memory
	if sbs != 0 {
		buffer = NewBuffer(sbs)
	}

	systemMonitor := &SystemMonitor{
		wg:       sync.WaitGroup{},
		settings: settings,
		logger:   logger,
		outChan:  outChan,
		buffer:   buffer,
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
		NewGPUNvidia(settings),
		NewGPUAMD(settings),
		NewGPUApple(settings),
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
					ts := timestamppb.Now()
					// store in buffer
					for k, v := range aggregatedMetrics {
						if sm.buffer != nil {
							sm.buffer.push(k, ts, v)
						}
					}

					// publish metrics
					record := makeStatsRecord(aggregatedMetrics, ts)
					// ensure that the context is not done before sending the record
					select {
					case <-sm.ctx.Done():
						return
					default:
						sm.outChan <- record
					}
					asset.ClearMetrics()
				}

				// reset samplesCollected
				samplesCollected = int32(0)
			}
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
