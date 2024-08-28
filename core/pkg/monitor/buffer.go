package monitor

import (
	"sync"

	"google.golang.org/protobuf/types/known/timestamppb"
)

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
