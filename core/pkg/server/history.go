package server

import (
	"github.com/wandb/wandb/core/pkg/service"
)

type ActiveHistory struct {
	values map[string]*service.HistoryItem
	step   int64
	flush  func(*service.HistoryStep, []*service.HistoryItem)
}

type ActiveHistoryOptions func(ac *ActiveHistory)

func NewActiveHistory(opts ...ActiveHistoryOptions) *ActiveHistory {
	ah := &ActiveHistory{
		values: make(map[string]*service.HistoryItem),
	}

	for _, opt := range opts {
		opt(ah)
	}
	return ah
}

func WithFlush(flush func(*service.HistoryStep, []*service.HistoryItem)) ActiveHistoryOptions {
	return func(ac *ActiveHistory) {
		ac.flush = flush
	}
}

func WithStep(step int64) ActiveHistoryOptions {
	return func(ac *ActiveHistory) {
		ac.step = step
	}
}

func (ah *ActiveHistory) Clear() {
	clear(ah.values)
}

func (ah *ActiveHistory) UpdateValues(values []*service.HistoryItem) {
	for _, value := range values {
		ah.values[value.GetKey()] = value
	}
}

func (ah *ActiveHistory) UpdateStep(step int64) {
	ah.step = step
}

func (ah *ActiveHistory) GetStep() *service.HistoryStep {
	step := &service.HistoryStep{
		Num: ah.step,
	}
	return step
}

func (ah *ActiveHistory) GetItem(key string) (*service.HistoryItem, bool) {
	if value, ok := ah.values[key]; ok {
		return value, ok
	}
	return nil, false
}

func (ah *ActiveHistory) GetValues() []*service.HistoryItem {
	var values []*service.HistoryItem
	for _, value := range ah.values {
		values = append(values, value)
	}
	return values
}

func (ah *ActiveHistory) Flush() {
	if ah == nil {
		return
	}
	if ah.flush != nil {
		ah.flush(ah.GetStep(), ah.GetValues())
	}
	ah.Clear()
}
