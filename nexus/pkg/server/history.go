package server

import (
	"container/heap"
	"encoding/json"
	"fmt"
	"math"
	"math/rand"
	"sort"
	"strconv"
	"strings"

	"github.com/wandb/wandb/nexus/internal/nexuslib"
	"github.com/wandb/wandb/nexus/pkg/service"
)

type Item[T comparable] struct {
	value     T
	priority  float64
	timestamp int
}

func (item Item[T]) String() string {
	return fmt.Sprintf("%v", item.value)
}

type PriorityQueue[T comparable] []*Item[T]

func (pq PriorityQueue[T]) Len() int           { return len(pq) }
func (pq PriorityQueue[T]) Less(i, j int) bool { return pq[i].priority < pq[j].priority }
func (pq PriorityQueue[T]) Swap(i, j int)      { pq[i], pq[j] = pq[j], pq[i] }

func (pq *PriorityQueue[T]) Push(x interface{}) {
	item := x.(*Item[T])
	*pq = append(*pq, item)
}

func (pq *PriorityQueue[T]) Pop() interface{} {
	old := *pq
	n := len(old)
	item := old[n-1]
	*pq = old[0 : n-1]
	return item
}

type ReservoirSampling[T comparable] struct {
	waitingList PriorityQueue[T]
	k           int
	delta       float64
	j           int
}

func (r *ReservoirSampling[T]) computeQ(j int) float64 {
	gamma := -math.Log(r.delta) / float64(j)
	ratio := float64(r.k) / float64(j)
	return math.Min(1, ratio+gamma+math.Sqrt(math.Pow(gamma, 2)+2*gamma*ratio))
}

func (r *ReservoirSampling[T]) Add(value T) {
	x := rand.Float64()
	if x < r.computeQ(r.j+1) {
		item := &Item[T]{value: value, priority: x, timestamp: r.j}
		heap.Push(&r.waitingList, item)
	}
	r.j += 1
}

func (r *ReservoirSampling[T]) GetSample() []T {
	k := min(r.k, r.waitingList.Len())
	result := make([]*Item[T], k)

	for i := 0; i < k; i++ {
		item := heap.Pop(&r.waitingList).(*Item[T])
		result[i] = item
	}
	sort.Slice(result, func(i, j int) bool {
		return result[i].timestamp < result[j].timestamp
	})

	values := make([]T, k)
	for i := 0; i < k; i++ {
		values[i] = result[i].value
	}

	return values
}

func (h *Handler) sampleHistory(history *service.HistoryRecord) {
	var value float32
	if h.sampledHistory == nil {
		h.sampledHistory = make(map[string]*ReservoirSampling[float32])
	}
	for _, item := range history.GetItem() {
		err := json.Unmarshal([]byte(item.ValueJson), &value)
		if err != nil {
			continue
		}
		if _, ok := h.sampledHistory[item.Key]; !ok {
			h.sampledHistory[item.Key] = &ReservoirSampling[float32]{
				k:     48,
				delta: 0.0005,
			}
		}
		h.sampledHistory[item.Key].Add(value)
	}
}

// handleHistory handles a history record. This is the main entry point for history records.
// It is responsible for handling the history record internally, processing it,
// and forwarding it to the Writer.
func (h *Handler) handleHistory(history *service.HistoryRecord) {
	if history.GetItem() == nil {
		return
	}

	// TODO replace history encoding with a map, this will make it easier to handle history
	historyMap := make(map[string]string)
	for _, item := range history.GetItem() {
		historyMap[item.GetKey()] = item.GetValueJson()
	}

	h.handleHistoryInternal(history, &historyMap)
	h.handleAllHistoryMetric(history, &historyMap)

	h.sampleHistory(history)

	record := &service.Record{
		RecordType: &service.Record_History{History: history},
	}
	h.sendRecord(record)

	// TODO unify with handleSummary
	// TODO add an option to disable summary (this could be quite expensive)
	summaryRecord := nexuslib.ConsolidateSummaryItems(h.consolidatedSummary, history.Item)
	h.sendRecord(summaryRecord)
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
			runTime = val - h.timer.GetStartTimeMicro()
		}
	}
	history.Item = append(history.Item,
		&service.HistoryItem{Key: "_runtime", ValueJson: fmt.Sprintf("%f", runTime)},
		&service.HistoryItem{Key: "_step", ValueJson: fmt.Sprintf("%d", history.GetStep().GetNum())},
	)
}

// handleAllHistoryMetric handles all history items. It is responsible for matching current history
// items with defined metrics, and creating new metrics if needed. It also handles step metric in case
// it needs to be synced, but not part of the history record.
func (h *Handler) handleAllHistoryMetric(history *service.HistoryRecord, historyMap *map[string]string) {
	// This means that there are no metrics defined, and we don't need to do anything
	if h.mh == nil {
		return
	}

	for _, item := range history.GetItem() {
		h.imputeStepMetric(item, history, historyMap)
	}
}

// imputeStepMetric imputes a step metric if it needs to be synced, but not part of the history record.
func (h *Handler) imputeStepMetric(item *service.HistoryItem, history *service.HistoryRecord, historyMap *map[string]string) {

	// check if history item matches a defined metric or a glob metric
	metric := h.matchHistoryItemMetric(item)

	key := metric.GetStepMetric()
	// check if step metric is defined and if it needs to be synced
	if !(metric.GetOptions().GetStepSync() && key != "") {
		return
	}

	// check if step metric is already in history
	if _, ok := (*historyMap)[key]; ok {
		return
	}

	// we use the summary value of the metric as the algorithm for imputing the step metric
	if value, ok := h.consolidatedSummary[key]; ok {
		(*historyMap)[key] = value
		hi := &service.HistoryItem{
			Key:       key,
			ValueJson: value,
		}
		history.Item = append(history.Item, hi)
	}
}

// matchHistoryItemMetric matches a history item with a defined metric or creates a new metric if needed.
func (h *Handler) matchHistoryItemMetric(item *service.HistoryItem) *service.MetricRecord {

	// ignore internal history items
	if strings.HasPrefix(item.Key, "_") {
		return nil
	}

	// check if history item matches a defined metric exactly, if it does return the metric
	if metric, ok := h.mh.definedMetrics[item.Key]; ok {
		return metric
	}

	// if a new metric was created, we need to handle it
	metric := h.mh.createMatchingGlobMetric(item.Key)
	if metric != nil {
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
	return metric
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

func (h *Handler) handleSampledHistory(record *service.Record, response *service.Response) {
	if h.sampledHistory == nil {
		return
	}
	var items []*service.SampledHistoryItem

	for key, sampler := range h.sampledHistory {
		values := sampler.GetSample()
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
