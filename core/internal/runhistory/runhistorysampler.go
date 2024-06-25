package runhistory

import (
	"strings"

	json "github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/sampler"
	"github.com/wandb/wandb/core/pkg/service"
)

// RunHistorySampler tracks a sample of each metric in the run's history.
type RunHistorySampler struct {
	samples map[metricKey]*sampler.ReservoirSampler[float32]
}

func NewRunHistorySampler() *RunHistorySampler {
	return &RunHistorySampler{
		samples: make(map[metricKey]*sampler.ReservoirSampler[float32]),
	}
}

// SampleNext updates all samples with the next history row.
//
// This must be called on history rows in order.
func (s *RunHistorySampler) SampleNext(history *service.HistoryRecord) {
	for _, item := range history.Item {

		value, err := json.Unmarshal([]byte(item.ValueJson))
		if err != nil {
			// Skip items that we cannot sample.
			continue
		}

		key := getMetricKey(item)

		sample, ok := s.samples[key]
		if !ok {
			sample = sampler.NewReservoirSampler[float32](48, 0.0005)
			s.samples[key] = sample
		}

		sample.Add(value.(float32))
	}
}

// Get returns all the samples.
func (s *RunHistorySampler) Get() []*service.SampledHistoryItem {
	items := make([]*service.SampledHistoryItem, 0, len(s.samples))

	for metricKey, sample := range s.samples {
		items = append(items,
			sampledHistoryItem(metricKey, sample.Sample()))
	}

	return items
}

// metricKey is the slash-separated path for a metric.
type metricKey string

// getMetricKey returns a representation of the item's key.
func getMetricKey(item *service.HistoryItem) metricKey {
	if item.Key != "" {
		return metricKey(item.Key)
	} else {
		return metricKey(strings.Join(item.NestedKey, "/"))
	}
}

// sampledHistoryItem creates an item with the correct key field.
func sampledHistoryItem(
	key metricKey,
	values []float32,
) *service.SampledHistoryItem {
	return &service.SampledHistoryItem{
		// NOTE: We only set Key, not NestedKey! It turns out the Python
		// code does not handle NestedKey and expects the slash-separated
		// result in Key instead.
		Key:         string(key),
		ValuesFloat: values,
	}
}
