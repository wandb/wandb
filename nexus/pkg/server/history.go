package server

import (
	"fmt"
	"strconv"
	"strings"

	"github.com/wandb/wandb/nexus/internal/nexuslib"
	"github.com/wandb/wandb/nexus/pkg/service"
)

// handleHistory handles a history record. This is the main entry point for history records.
// It is responsible for handling the history record internally, processing it for metrics,
// and forwarding it to the Writer.
func (h *Handler) handleHistory(history *service.HistoryRecord) {

	// TODO replace history encoding with a map
	if history.GetItem() == nil {
		return
	}

	historyMap := make(map[string]string)
	for _, item := range history.GetItem() {
		historyMap[item.GetKey()] = item.GetValueJson()
	}

	h.handleHistoryInternal(history, &historyMap)
	h.handleAllHistoryMetric(history, &historyMap)

	record := &service.Record{
		RecordType: &service.Record_History{History: history},
	}
	h.sendRecord(record)

	// TODO unify with handleSummary
	// TODO add an option to disable summary (this could be quite expensive)
	summaryRecord := nexuslib.ConsolidateSummaryItems(h.consolidatedSummary, history.Item)
	h.sendRecord(summaryRecord)
}

// handleSingleHistoryMetric handles a single history item. It is responsible for matching current history
// item with defined metrics, and creating new metrics if needed. It also handles step metric in case
// it needs to be synced with the metric, but not part of the history record.
func (h *Handler) handleSingleHistoryMetric(item *service.HistoryItem, historyMap *map[string]string) *service.HistoryItem {

	// ignore internal history items
	if strings.HasPrefix(item.Key, "_") {
		return nil
	}

	metric, created := h.mh.createMatchingGlobMetric(item.Key)
	if created {
		record := &service.Record{
			RecordType: &service.Record_Metric{
				Metric: metric,
			},
			Control: &service.Control{
				Local: true,
			},
		}
		h.handleMetric(record, metric)
	}

	// metric has a step metric, and we have not seen it before (and we are in step sync mode)
	// so we need to add it to the history record
	if metric.GetOptions().GetStepSync() && metric.GetStepMetric() != "" {
		key := metric.GetStepMetric()
		if _, ok := (*historyMap)[key]; ok {
			return nil
		}
		if value, ok := h.consolidatedSummary[key]; ok {
			(*historyMap)[key] = value
			return &service.HistoryItem{
				Key:       key,
				ValueJson: value,
			}
		}
	}
	return nil
}

// handleAllHistoryMetric handles all history items. It is responsible for matching current history
// items with defined metrics, and creating new metrics if needed. It also handles step metric in case
// it needs to be synced with the metric, but not part of the history record.
func (h *Handler) handleAllHistoryMetric(history *service.HistoryRecord, historyMap *map[string]string) {
	// This means that there are no definedMetrics to send hence we can return early
	if h.mh == nil {
		return
	}

	for _, item := range history.GetItem() {
		if hi := h.handleSingleHistoryMetric(item, historyMap); hi != nil {
			history.Item = append(history.Item, hi)
		}
	}
}

// handleHistoryInternal adds internal history items to the history record
// these items are used for internal bookkeeping and are not sent by the user
func (h *Handler) handleHistoryInternal(history *service.HistoryRecord, historyMap *map[string]string) {

	// TODO: add a timestamp field to the history record
	var runTime float64 = 0
	if value, ok := (*historyMap)["_timestamp"]; ok {
		val, err := strconv.ParseFloat(value, 64)
		if err != nil {
			h.logger.CaptureError("error parsing timestamp", err)
		} else {
			runTime = val - h.startTime
		}
	}
	history.Item = append(history.Item,
		&service.HistoryItem{Key: "_runtime", ValueJson: fmt.Sprintf("%f", runTime)},
		&service.HistoryItem{Key: "_step", ValueJson: fmt.Sprintf("%d", history.GetStep().GetNum())},
	)
}

// handlePartialHistory handles a partial history request. Collects the history items until a full
// history record is received.
func (h *Handler) handlePartialHistory(_ *service.Record, request *service.PartialHistoryRequest) {

	// This is the first partial history record we receive
	// for this step, so we need to initialize the history record
	// and step. If the user provided a step in the request,
	// use that, otherwise use 0.
	if h.historyRecord == nil {
		h.historyRecord = &service.HistoryRecord{}
		if request.Step != nil {
			h.historyRecord.Step = request.Step
		} else {
			h.historyRecord.Step = &service.HistoryStep{Num: h.runRecord.StartingStep}
		}
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
		if request.Step.Num > h.historyRecord.Step.Num {
			h.handleHistory(h.historyRecord)
			h.historyRecord = &service.HistoryRecord{
				Step: &service.HistoryStep{Num: request.Step.Num},
			}
		} else if request.Step.Num < h.historyRecord.Step.Num {
			h.logger.CaptureWarn("received history record for a step that has already been received",
				"received", request.Step, "current", h.historyRecord.Step)
			return
		}
	}

	// Append the history items from the request to the current history record.
	h.historyRecord.Item = append(h.historyRecord.Item, request.Item...)

	// Flush the history record and start to collect a new one with
	// the next step number.
	if (request.Step == nil && request.Action == nil) || (request.Action != nil && request.Action.Flush) {
		h.handleHistory(h.historyRecord)
		h.historyRecord = &service.HistoryRecord{
			Step: &service.HistoryStep{
				Num: h.historyRecord.Step.Num + 1,
			},
		}
	}
}
