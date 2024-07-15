package runhistory

import (
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/sampler"
	"github.com/wandb/wandb/core/pkg/service"
)

// RunHistorySampler tracks a sample of each metric in the run's history.
type RunHistorySampler struct {
	samples map[string]*sampler.ReservoirSampler[float32]
}

func NewRunHistorySampler() *RunHistorySampler {
	return &RunHistorySampler{
		samples: make(map[string]*sampler.ReservoirSampler[float32]),
	}
}

// SampleNext updates all samples with the next history row.
//
// This must be called on history rows in order.
func (s *RunHistorySampler) SampleNext(history *RunHistory) {
	// TODO: Support sampling nested metrics.
	history.ForEach(
		func(path pathtree.TreePath, value bool) bool { return true },
		func(path pathtree.TreePath, value int64) bool {
			if len(path) != 1 {
				return true
			}

			s.sampleInt(path[0], value)
			return true
		},
		func(path pathtree.TreePath, value float64) bool {
			if len(path) != 1 {
				return true
			}

			s.sampleFloat(path[0], value)
			return true
		},
		func(path pathtree.TreePath, value string) bool { return true },
	)
}

func (s *RunHistorySampler) sampleInt(key string, value int64) {
	s.sampleFloat(key, float64(value))
}

func (s *RunHistorySampler) sampleFloat(key string, value float64) {
	sample, ok := s.samples[key]
	if !ok {
		sample = sampler.NewReservoirSampler[float32](48, 0.0005)
		s.samples[key] = sample
	}
	sample.Add(float32(value))
}

// Get returns all the samples.
func (s *RunHistorySampler) Get() []*service.SampledHistoryItem {
	items := make([]*service.SampledHistoryItem, 0, len(s.samples))

	for metricKey, sample := range s.samples {
		items = append(items,
			&service.SampledHistoryItem{
				Key:         metricKey,
				ValuesFloat: sample.Sample(),
			})
	}

	return items
}
