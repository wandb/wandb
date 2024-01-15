package handler

import (
	"fmt"
	"strconv"

	"github.com/wandb/wandb/core/internal/debounce"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

type HistoryHandler struct {
	history  *Node[string]
	summary  *Node[string]
	delta    *Node[string]
	debounce *debounce.Debouncer
	step     int64
	init     bool
}

func NewHistoryHandler() *HistoryHandler {
	return &HistoryHandler{
		history: NewNode[string](nil, ""),
		summary: NewNode[string](nil, ""),
		delta:   NewNode[string](nil, ""),
		debounce: debounce.New(
			summaryDebouncerRateLimit,
			summaryDebouncerBurstSize,
			nil,
		),
	}
}

var hh = NewHistoryHandler()

func (h *Handler) FlushSummery() {
	if hh.summary.Value == nil {
		return
	}

	summary := &pb.SummaryRecord{}
	for k, v := range hh.summary.Flatten() {
		item := &pb.SummaryItem{
			Key:       k.Path[0],
			NestedKey: k.Path[1:],
			ValueJson: *v,
		}
		summary.Update = append(summary.Update, item)
	}

	h.sendRecord(&pb.Record{RecordType: &pb.Record_Summary{Summary: summary}})
	hh.summary = NewNode[string](nil, "")
}

func (h *Handler) flushHistory1() {
	if hh.history.Value == nil {
		return
	}

	value := fmt.Sprintf(`%d`, hh.step)
	hh.history.Add([]string{"step"}, &value)

	if t := hh.history.Get([]string{"_timestamp"}); t != nil {
		runtime := fmt.Sprintf(`%f`, 0.0)
		if value, err := strconv.ParseFloat(*t.Value, 64); err != nil {
			h.logger.CaptureError("error parsing timestamp", err)
		} else {
			runtime = fmt.Sprintf(`%f`, value-h.timer.GetStartTimeMicro())
		}
		hh.history.Add([]string{"_runtime"}, &runtime)
	}

	history := &pb.HistoryRecord{
		Step: &pb.HistoryStep{
			Num: hh.step,
		},
	}
	for k, v := range hh.history.Flatten() {
		item := &pb.HistoryItem{
			Key:       k.Path[0],
			NestedKey: k.Path[1:],
			ValueJson: *v,
		}
		history.Item = append(history.Item, item)
	}

	h.sampleHistory(history)
	h.sendRecord(&pb.Record{RecordType: &pb.Record_History{History: history}})

	hh.summary.Merge(hh.history)
	hh.delta.Merge(hh.history)
	hh.debounce.Set()
	hh.history = NewNode[string](nil, "")
}

func (h *Handler) HandleHistory1(request *pb.HistoryRecord) {
	step := request.GetStep()
	if step != nil {
		hh.step = step.GetNum()
	}

	for _, item := range request.GetItem() {
		path := append([]string{item.GetKey()}, item.GetNestedKey()...)
		value := item.GetValueJson()
		hh.history.Add(path, &value)
	}

	hh.step++
}

func (h *Handler) HandlePartialHistory1(request *pb.PartialHistoryRequest) {
	current := request.GetStep()
	action := request.GetAction()
	if !hh.init {
		switch {
		case current != nil:
			hh.step = current.GetNum()
		case h.runRecord != nil:
			hh.step = h.runRecord.StartingStep
		}
		hh.init = true
	}

	if current != nil {
		num := current.GetNum()
		if num > hh.step {
			h.flushHistory1()
			hh.step = num
		} else if num < hh.step {
			return // ignore
		}
	}

	for _, item := range request.GetItem() {
		path := append([]string{item.GetKey()}, item.GetNestedKey()...)
		value := item.GetValueJson()
		hh.history.Add(path, &value)
	}

	if (current == nil && action == nil) || action.GetFlush() {
		h.flushHistory1()
		hh.step++
	}
}

func (h *Handler) HandleSummary1(request *pb.SummaryRecord) {
	for _, item := range request.GetUpdate() {
		path := append([]string{item.GetKey()}, item.GetNestedKey()...)
		value := item.GetValueJson()
		hh.delta.Add(path, &value)
	}

	runtime := int32(h.timer.Elapsed().Seconds())
	value := fmt.Sprintf(`%d`, runtime)
	hh.delta.Add([]string{"_wandb", "runtime"}, &value)

	hh.summary.Merge(hh.delta)
	hh.debounce.Set()
}
