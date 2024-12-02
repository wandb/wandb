package monitor

import (
	"slices"
	"sync"

	"github.com/wandb/simplejsonext"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// Measurement represents a single metric measurement with a timestamp and value.
type Measurement struct {
	Timestamp *timestamppb.Timestamp
	Value     float64
}

// Measurements holds a thread-safe list of Measurement objects with a maximum size.
type Measurements struct {
	elements []Measurement
	maxSize  int32
	mutex    sync.Mutex
}

// Append adds a new Measurement to the list, maintaining the maxSize constraint.
func (m *Measurements) Append(element Measurement) {
	m.mutex.Lock()
	defer m.mutex.Unlock()
	if m.maxSize > 0 && int32(len(m.elements)) >= m.maxSize {
		// Drop the oldest element
		m.elements = m.elements[1:]
	}
	m.elements = append(m.elements, element)
}

// Elements returns a copy of the measurements in the list.
func (m *Measurements) Elements() []Measurement {
	m.mutex.Lock()
	defer m.mutex.Unlock()
	return slices.Clone(m.elements)
}

// Buffer is the in-memory metrics buffer for the system monitor.
type Buffer struct {
	elements map[string]*Measurements
	mutex    sync.RWMutex
	maxSize  int32
}

// NewBuffer creates a new Buffer with the specified maximum size for each metric's measurements.
func NewBuffer(maxSize int32) *Buffer {
	return &Buffer{
		elements: make(map[string]*Measurements),
		maxSize:  maxSize,
	}
}

// Push adds the metrics from a StatsRecord to the buffer.
func (mb *Buffer) Push(metrics *spb.StatsRecord) {
	if mb == nil {
		return
	}

	for _, item := range metrics.Item {
		k := item.Key
		ts := metrics.Timestamp
		v := item.ValueJson

		// unmashal the value to a float64 and push it to the buffer
		if v, err := simplejsonext.UnmarshalString(v); err == nil {
			if v, ok := v.(float64); ok {
				mb.push(k, ts, v)
			}
		}
	}
}

// Push adds a new measurement to the buffer for the given metric name.
func (mb *Buffer) push(metricName string, timeStamp *timestamppb.Timestamp, metricValue float64) {
	mb.mutex.Lock()
	defer mb.mutex.Unlock()
	m, ok := mb.elements[metricName]
	if !ok {
		m = &Measurements{
			maxSize: mb.maxSize,
		}
		mb.elements[metricName] = m
	}
	m.Append(Measurement{
		Timestamp: timeStamp,
		Value:     metricValue,
	})
}

// GetMeasurements retrieves the measurements for the specified metric name.
func (mb *Buffer) GetMeasurements() map[string][]Measurement {
	mb.mutex.RLock()
	defer mb.mutex.RUnlock()
	allMeasurements := make(map[string][]Measurement, len(mb.elements))
	for metricName, measurements := range mb.elements {
		allMeasurements[metricName] = measurements.Elements()
	}
	return allMeasurements
}
