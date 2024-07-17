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
	history.ForEachNumber(
		func(path pathtree.TreePath, value float64) bool {
			if path.Len() != 1 {
				return true
			}

			key := path.Labels()[0]

			sample, ok := s.samples[key]
			if !ok {
				sample = sampler.NewReservoirSampler[float32](48, 0.0005)
				s.samples[key] = sample
			}
			sample.Add(float32(value))

			return true
		},
	)
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
