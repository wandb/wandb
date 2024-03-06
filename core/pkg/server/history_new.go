package server

import (
	"fmt"
	"strconv"

	"github.com/wandb/wandb/core/internal/debounce"
	"github.com/wandb/wandb/core/pkg/service"
)

type EventHandler struct {
	history  *Node[string]
	summary  *Node[string]
	delta    *Node[string]
	step     int64
	init     bool
	debuncer *debounce.Debouncer
	timer    *Timer
}

var event = &EventHandler{
	history: NewNode[string]("", ""),
	summary: NewNode[string]("", ""),
	delta:   NewNode[string]("", ""),
	debuncer: debounce.NewDebouncer(
		summaryDebouncerRateLimit,
		summaryDebouncerBurstSize,
		nil,
	),
	timer: &Timer{},
}

func FlushHistory(h *Handler) {
	if item := event.history.Get([]string{"_timestamp"}); item != nil {
		value := item.Value
		if v, err := strconv.ParseFloat(value, 64); err == nil {
			event.history.Add([]string{"_runtime"}, fmt.Sprintf("%f", v))
		}
	}
	event.history.Add([]string{"_step"}, fmt.Sprintf("%d", event.step))

	items := make([]*service.HistoryItem, 0)
	for key, value := range event.history.Leaves() {
		item := &service.HistoryItem{
			Key:       key.Path[0],
			NestedKey: key.Path[1:],
			ValueJson: value,
		}
		items = append(items, item)
	}
	record := &service.Record{
		RecordType: &service.Record_History{
			History: &service.HistoryRecord{
				Step: &service.HistoryStep{
					Num: event.step,
				},
				Item: items,
			},
		},
	}
	h.sendRecord(record)

	event.delta.Merge(event.history)
	event.summary.Merge(event.history)
	event.debuncer.SetNeedsDebounce()
	event.history = NewNode[string]("", "")
}

func HandlePartialHistory(request *service.PartialHistoryRequest) {
	if !event.init {
		event.init = true
		event.step = request.GetStep().GetNum()
	}

	if request.GetStep() != nil {
		step := request.GetStep().GetNum()
		if step > event.step {
			FlushHistory(nil) // TODO: fix this
			event.step = step
		}
	}

	for _, item := range request.GetItem() {
		path := append([]string{item.GetKey()}, item.GetNestedKey()...)
		event.history.Add(path, item.GetValueJson())
	}

	if (request.GetStep() == nil && request.GetAction() == nil) || request.GetAction().GetFlush() {
		FlushHistory(nil) // TODO: fix this
		event.step++
	}
}

func HandleHistory(record *service.HistoryRecord) {
	event.step = record.GetStep().GetNum()

	for _, item := range record.GetItem() {
		path := append([]string{item.GetKey()}, item.GetNestedKey()...)
		event.history.Add(path, item.GetValueJson())
	}
	FlushHistory(nil) // TODO: fix this
}

func HandleSummary(record *service.SummaryRecord) {
	for _, item := range record.GetUpdate() {
		path := append([]string{item.GetKey()}, item.GetNestedKey()...)
		event.delta.Add(path, item.GetValueJson())
	}

	runtime := int32(event.timer.Elapsed().Seconds())
	event.delta.Add([]string{"_wandb", "_runtime"}, fmt.Sprintf("%d", runtime))

	event.summary.Merge(event.delta)
	event.debuncer.SetNeedsDebounce()
}

func HandleSummaryDebouncer(h *Handler) {
	items := make([]*service.SummaryItem, 0)
	for k, v := range event.delta.Leaves() {
		item := &service.SummaryItem{
			Key:       k.Path[0],
			NestedKey: k.Path[1:],
			ValueJson: v,
		}
		items = append(items, item)
	}
	record := &service.Record{
		RecordType: &service.Record_Summary{
			Summary: &service.SummaryRecord{
				Update: items,
			},
		},
	}
	h.sendRecord(record)
	event.delta = NewNode[string]("", "")
}
