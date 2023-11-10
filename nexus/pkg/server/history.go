package server

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"

	"github.com/wandb/wandb/nexus/pkg/server/history"
	"github.com/wandb/wandb/nexus/pkg/service"
	"google.golang.org/protobuf/proto"
)

func (h *Handler) handleSampledHistory(record *service.Record, response *service.Response) {
	samples := h.sm.Samples()
	if samples == nil {
		return
	}

	var items []*service.SampledHistoryItem

	for key, values := range samples {
		item := &service.SampledHistoryItem{
			Key:         key,
			ValuesFloat: values,
		}
		items = append(items, item)
	}

	response.ResponseType = &service.Response_SampledHistoryResponse{
		SampledHistoryResponse: &service.SampledHistoryResponse{
			Item: items,
		},
	}
}

// handlePartialHistory handles a partial history request. Collects the history items until a full
// history record is received.
func (h *Handler) handlePartialHistory(_ *service.Record, request *service.PartialHistoryRequest) {

	// This is the first partial history record we receive
	// for this step, so we need to initialize the history record
	// and step. If the user provided a step in the request,
	// use that, otherwise use 0.
	if h.has == nil {
		step := h.runRecord.StartingStep
		if request.Step != nil {
			step = request.Step.Num
		}
		h.has = history.NewActiveSet(step, func(step int64, items map[string]*service.HistoryItem) {
			history := &service.HistoryRecord{
				Step: &service.HistoryStep{Num: step},
			}
			for _, item := range items {
				history.Item = append(history.Item, item)
			}
			h.handleHistory(history)
		})
	}

	// The HistoryRecord struct is responsible for tracking data related to
	//	a single step in the history. Users can send multiple partial history
	//	records for a single step. Each partial history record contains a
	//	step number, a flush flag, and a list of history items.
	//
	// The step number indicates the step number for the history record. The
	// flush flag determines whether the history record should be flushed
	// after processing the request. The history items are appended to the
	// existing history record.
	//
	// The following logic is used to process the request:
	//
	// -  If the request includes a step number and the step number is greater
	//		than the current step number, the current history record is flushed
	//		and a new history record is created.
	// - If the step number in the request is less than the current step number,
	//		we ignore the request and log a warning.
	// 		NOTE: the server requires the steps of the history records
	// 		to be monotonically increasing.
	// -  If the step number in the request matches the current step number, the
	//		history items are appended to the current history record.
	//
	// - If the request has a flush flag, another flush might occur after for the
	// current history record after processing the request.
	//
	// - If the request doesn't have a step, and doesn't have a flush flag, this is
	//	equivalent to step being equal to the current step number and a flush flag
	//	being set to true.
	if request.Step != nil {
		step := h.has.GetIdx()
		if request.Step.Num > step {
			h.has.FlushWithIdx(request.Step.Num)
		} else if request.Step.Num < step {
			h.logger.CaptureWarn("received history record for a step that has already been received",
				"received", request.Step, "current", step)
			return
		}
	}

	// Append the history items from the request to the current history record.
	h.has.Updates(request.Item...)

	// Flush the history record and start to collect a new one with
	// the next step number.
	if (request.Step == nil && request.Action == nil) || (request.Action != nil && request.Action.Flush) {
		h.has.Flush()
	}
}

// handleHistory handles a history record. This is the main entry point for history records.
// It is responsible for handling the history record internally, processing it,
// and forwarding it to the Writer.
func (h *Handler) handleHistory(record *service.HistoryRecord) {
	if record.GetItem() == nil {
		return
	}

	// TODO replace history encoding with a map, this will make it easier to handle history
	if h.has == nil {
		h.has = history.NewActiveSet[*service.HistoryItem](record.GetStep().GetNum(), nil)
		h.has.Updates(record.GetItem()...)
	}

	// TODO: add a timestamp field to the history record
	var runTime float64 = 0
	if value, ok := h.has.GetValue("_timestamp"); ok {
		if val, err := strconv.ParseFloat(value, 64); err != nil {
			h.logger.CaptureError("error parsing timestamp", err)
		} else {
			runTime = val - h.timer.GetStartTimeMicro()
		}
	}
	h.has.Updates(
		&service.HistoryItem{Key: "_runtime", ValueJson: fmt.Sprintf("%f", runTime)},
		&service.HistoryItem{Key: "_step", ValueJson: fmt.Sprintf("%d", record.GetStep().GetNum())},
	)

	if h.mm != nil {
		for _, item := range record.GetItem() {
			key := h.imputeStepMetric(item.GetKey())
			if key == "" {
				continue
			}
			// check if step metric is already in history
			if _, ok := h.has.Get(key); ok {
				continue
			}
			// we use the summary value of the metric as the algorithm for imputing the step metric
			if value, ok := h.csas.Get(key); ok {
				h.has.Updates(
					&service.HistoryItem{
						Key:       value.GetKey(),
						NestedKey: item.GetNestedKey(),
						ValueJson: value.GetValueJson(),
					},
				)
			}
		}
	}

	flush_record := &service.Record{
		RecordType: &service.Record_History{
			History: &service.HistoryRecord{
				Item: h.has.Gets(),
				Step: record.GetStep(),
			},
		},
	}
	h.sendRecord(flush_record)

	// sample history
	if h.sm == nil {
		h.sm = history.NewSampleManager[float32](48, 0.0005)
	}
	var value float32
	for _, item := range record.GetItem() {
		err := json.Unmarshal([]byte(item.ValueJson), &value)
		if err != nil {
			continue
		}
		h.sm.Add(item.GetKey(), value)
	}

	// TODO unify with handleSummary
	// TODO add an option to disable summary (this could be quite expensive)
	var items []*service.SummaryItem
	for _, item := range record.GetItem() {
		items = append(items, &service.SummaryItem{
			Key:       item.GetKey(),
			NestedKey: item.GetNestedKey(),
			ValueJson: item.GetValueJson(),
		})
		summary := &service.SummaryRecord{
			Update: items,
		}

		h.updateSummaryDelta(summary)
	}
}

// imputeStepMetric imputes a step metric if it needs to be synced, but not part of the history record.
func (h *Handler) imputeStepMetric(key string) string {

	// ignore internal history items
	if strings.HasPrefix(key, "_") {
		return ""
	}

	// check if history item matches a defined metric or a glob metric
	var metric *service.MetricRecord
	// check if history item matches a defined metric exactly, if it does we can use it
	if value, ok := h.mm.GetDefinedMetricKeySet().Get(key); ok {
		metric = value
	} else if value, ok := h.mm.GetGlobMetricKeySet().Match(key); ok {
		// if a new metric was created, we need to handle it
		metric = proto.Clone(value).(*service.MetricRecord)
		metric.Name = key
		metric.Options.Defined = false
		metric.GlobName = ""
		record := &service.Record{
			RecordType: &service.Record_Metric{
				Metric: metric,
			},
			Control: &service.Control{
				Local: true,
			},
		}
		h.handleMetric(record, metric)
	} else {
		return ""
	}

	// check if step metric is defined and if it needs to be synced
	if !metric.GetOptions().GetStepSync() {
		return ""
	}
	return metric.GetStepMetric()
}
