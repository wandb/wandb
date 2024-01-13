package handler

import (
	"github.com/wandb/wandb/core/internal/debounce"
	"github.com/wandb/wandb/core/internal/observability"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

const (
	summaryDebouncerRateLimit = 1 / 30.0 // todo: audit rate limit
	summaryDebouncerBurstSize = 1        // todo: audit burst size
)

type Summary struct {
	// Consolidated is the full summary (all keys)
	// TODO(memory): persist this in the future as it will grow with number of distinct keys
	Consolidated map[string]string

	// Delta is the delta summary (keys updated since the last time we sent summary)
	Delta map[string]string

	// summaryDebouncer is the debouncer for summary updates
	summaryDebouncer *debounce.Debouncer
}

func NewSummary(logger *observability.CoreLogger) *Summary {
	return &Summary{
		Consolidated: make(map[string]string),
		Delta:        make(map[string]string),
		summaryDebouncer: debounce.New(
			summaryDebouncerRateLimit,
			summaryDebouncerBurstSize,
			logger,
		),
	}
}

func (s *Summary) Debounce(f func()) {
	if s == nil || s.summaryDebouncer == nil {
		return
	}
	s.summaryDebouncer.Debounce(f)
}

func (s *Summary) Flush(f func()) {
	s.summaryDebouncer.Flush(f)
}

func (s *Summary) UpdateDelta(summaryRecord *pb.Record) {
	for _, item := range summaryRecord.GetSummary().GetUpdate() {
		s.Delta[item.GetKey()] = item.GetValueJson()
	}
	s.summaryDebouncer.Set()
}
