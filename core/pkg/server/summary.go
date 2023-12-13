package server

import (
	"github.com/wandb/wandb/core/internal/debounce"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

type SummaryHandler struct {
	// consolidatedSummary is the full summary (all keys)
	// TODO(memory): persist this in the future as it will grow with number of distinct keys
	consolidatedSummary map[string]string

	// summaryDelta is the delta summary (keys updated since the last time we sent summary)
	summaryDelta map[string]string

	// summaryDebouncer is the debouncer for summary updates
	summaryDebouncer *debounce.Debouncer
}

func NewSummaryHandler(logger *observability.CoreLogger) *SummaryHandler {
	return &SummaryHandler{
		consolidatedSummary: make(map[string]string),
		summaryDelta:        make(map[string]string),
		summaryDebouncer: debounce.NewDebouncer(
			summaryDebouncerRateLimit,
			summaryDebouncerBurstSize,
			logger,
		),
	}
}

func (sh *SummaryHandler) Debounce(f func()) {
	if sh == nil || sh.summaryDebouncer == nil {
		return
	}
	sh.summaryDebouncer.Debounce(f)
}

func (sh *SummaryHandler) Flush(f func()) {
	sh.summaryDebouncer.Flush(f)
}

func (sh *SummaryHandler) updateSummaryDelta(summaryRecord *service.Record) {
	for _, item := range summaryRecord.GetSummary().GetUpdate() {
		sh.summaryDelta[item.GetKey()] = item.GetValueJson()
	}
	sh.summaryDebouncer.SetNeedsDebounce()
}

func (sh *SummaryHandler) GetConsolidatedSummary() map[string]string {
	return sh.consolidatedSummary
}
