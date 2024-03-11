package server

import (
	"container/heap"
	"fmt"
	"math"
	"math/rand"
	"sort"
	"strconv"

	"github.com/segmentio/encoding/json"

	"github.com/wandb/wandb/core/internal/corelib"
	"github.com/wandb/wandb/core/pkg/service"
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

// flushHistory flushes a history record. It is responsible for handling the history record internally,
// processing it, and forwarding it to the Writer.
func (h *Handler) flushHistory(history *service.HistoryRecord) {
	if history.GetItem() == nil {
		return
	}

	// adds internal history items to the history record
	// these items are used for internal bookkeeping and are not sent by the user
	// TODO: add a timestamp field to the history record
	var runTime float64 = 0
	if item, ok := h.activeHistory.GetItem("_timestamp"); ok {
		value := item.GetValueJson()
		val, err := strconv.ParseFloat(value, 64)
		if err != nil {
			h.logger.CaptureError("error parsing timestamp", err)
		} else {
			runTime = val - h.timer.GetStartTimeMicro()
		}
	}
	history.Item = append(history.Item,
		&service.HistoryItem{Key: "_runtime", ValueJson: fmt.Sprintf("%f", runTime)},
	)
	if !h.settings.GetXShared().GetValue() {
		history.Item = append(history.Item,
			&service.HistoryItem{Key: "_step", ValueJson: fmt.Sprintf("%d", history.GetStep().GetNum())},
		)
	}

	// handles all history items. It is responsible for matching current history
	// items with defined metrics, and creating new metrics if needed. It also handles step metric in case
	// it needs to be synced, but not part of the history record.
	// This means that there are metrics defined for this run
	if h.metricHandler != nil {
		for _, item := range history.GetItem() {
			step := h.imputeStepMetric(item)
			// TODO: fix this, we update history while we are iterating over it
			// TODO: handle nested step metrics (e.g. step defined by another step)
			if step != nil {
				history.Item = append(history.Item, step)
			}
		}
	}

	h.sampleHistory(history)

	record := &service.Record{
		RecordType: &service.Record_History{History: history},
	}
	h.sendRecord(record)

	// TODO unify with handleSummary
	// TODO add an option to disable summary (this could be quite expensive)
	if h.summaryHandler == nil {
		return
	}
	summary := corelib.ConsolidateSummaryItems(h.summaryHandler.consolidatedSummary, history.GetItem())
	h.summaryHandler.updateSummaryDelta(summary)
}
