package runhistory

import (
	"math/rand/v2"
	"strconv"

	"github.com/wandb/wandb/core/internal/sampler"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// RunHistorySampler tracks a sample of each metric in the run's history.
type RunHistorySampler struct {
	rand    *rand.Rand
	samples map[string]*sampler.ReservoirSampler[float32]
}

func NewRunHistorySampler() *RunHistorySampler {
	return &RunHistorySampler{
		rand:    rand.New(rand.NewPCG(rand.Uint64(), rand.Uint64())),
		samples: make(map[string]*sampler.ReservoirSampler[float32]),
	}
}

// SampleNext updates all samples with the next history row.
//
// This must be called on history rows in order.
func (s *RunHistorySampler) SampleNext(history *spb.HistoryRecord) {
	for _, item := range history.Item {
		var key string
		if len(item.GetNestedKey()) == 1 {
			// TODO: Support sampling nested metrics.
			key = item.GetNestedKey()[0]
		} else {
			key = item.GetKey()
		}

		if key == "" {
			continue // Ignore invalid records.
		}

		value, err := strconv.ParseFloat(item.GetValueJson(), 32)
		if err != nil {
			continue // Only sample numeric metrics.
		}

		sample, ok := s.samples[key]
		if !ok {
			sample = sampler.NewReservoirSampler[float32](s.rand, 48)
			s.samples[key] = sample
		}
		sample.Add(float32(value))
	}
}

// Get returns all the samples.
func (s *RunHistorySampler) Get() []*spb.SampledHistoryItem {
	items := make([]*spb.SampledHistoryItem, 0, len(s.samples))

	for metricKey, sample := range s.samples {
		items = append(items,
			&spb.SampledHistoryItem{
				Key:         metricKey,
				ValuesFloat: sample.Sample(),
			})
	}

	return items
}
