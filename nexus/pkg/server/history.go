package server

import (
	"fmt"
	"github.com/wandb/wandb/nexus/internal/nexuslib"
	"github.com/wandb/wandb/nexus/pkg/service"
	"strconv"
)

// handleHistory handles a history record. This is the main entry point for history records.
func (h *Handler) handleHistory(history *service.HistoryRecord) {

	if history.GetItem() == nil {
		return
	}

	h.handleInternal(history)
	h.handleMetricHistory(history)

	record := &service.Record{
		RecordType: &service.Record_History{History: history},
	}
	h.sendRecord(record)

	// TODO unify with handleSummary
	summaryRecord := nexuslib.ConsolidateSummaryItems(h.consolidatedSummary, history.Item)
	h.sendRecord(summaryRecord)
}

// handleInternal adds internal history items to the history record
func (h *Handler) handleInternal(history *service.HistoryRecord) {
	// walk through items looking for _timestamp
	// TODO: add a timestamp field to the history record
	items := history.GetItem()
	var runTime float64 = 0
	for _, item := range items {
		if item.Key == "_timestamp" {
			val, err := strconv.ParseFloat(item.ValueJson, 64)
			if err != nil {
				h.logger.CaptureError("error parsing timestamp", err)
			} else {
				runTime = val - h.startTime
			}
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
