package stream

import (
	"sync"
	"sync/atomic"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/runwork"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// FlowControlBuffer is the FlowControl channel's internal buffer.
//
// This is safe for use by at most two goroutines: one calling Add and
// eventually Close, and another calling Get.
//
// If all work were saveable, this would essentially be two integers.
// But since some work is not saved to the transaction log (like Requests),
// we represent the buffer as an alternating sequence of saved work chunks
// and non-saved work (stored in memory).
type FlowControlBuffer struct {
	// data is a compressed channel of work.
	data chan FlowControlBufferItem

	// lastItem is the item at the back of data or nil.
	lastItem FlowControlBufferItem

	// lastItemMu guarantees that we don't modify lastItem after returning
	// it from Get.
	lastItemMu sync.Mutex

	// inMemorySize is FlowControlParams.InMemorySize.
	inMemorySize int

	// offloadingCancelled is whether StopOffloading was called.
	offloadingCancelled atomic.Bool

	// backedUpCount indicates when Get is being called slower than Add.
	//
	// It is incremented whenever Add offloads an item.
	//
	// When above zero, all saved work is offloaded despite inMemorySize.
	// It is reset to 0 once Get is called when the channel is empty.
	backedUpCount atomic.Uint32

	// sentOverflowTelemetry is whether the flow control overflow telemetry
	// flag has already been set.
	sentOverflowTelemetry bool

	logger    *observability.CoreLogger
	runHandle *runhandle.RunHandle
}

type FlowControlBufferWork struct {
	Work runwork.Work
}

type FlowControlBufferSavedChunk struct {
	// InitialOffset is the byte offset in the transaction log at which the
	// first record is saved.
	InitialOffset int64

	// InitialNumber is the record number of the first record in this chunk.
	InitialNumber int64

	// Count is the number of records represented by this chunk.
	Count int64
}

type FlowControlBufferItem interface {
	Switch(
		func(work runwork.Work),
		func(chunk *FlowControlBufferSavedChunk),
	)
}

func (work *FlowControlBufferWork) Switch(
	fn func(work runwork.Work),
	_ func(chunk *FlowControlBufferSavedChunk),
) {
	fn(work.Work)
}

func (chunk *FlowControlBufferSavedChunk) Switch(
	_ func(work runwork.Work),
	fn func(chunk *FlowControlBufferSavedChunk),
) {
	fn(chunk)
}

type FlowControlParams struct {
	// InMemorySize is the maximum number of saved Work values to keep in memory
	// to avoid having to read the transaction log.
	//
	// If there are fewer than this many items in the buffer, incoming Work
	// is stored in the buffer directly regardless of whether it's saved.
	// Otherwise, saved Work values are discarded and later read from the
	// transaction log. Unsaved Work is always kept in memory.
	InMemorySize int

	// Limit is the buffer size of the internal channel.
	//
	// This must be greater than InMemorySize, or else this acts as
	// a finitely-buffered channel with no offloading of data.
	//
	// While the buffer can represent an unlimited amount of saved Work,
	// unsaved Work is stored directly in the channel. This limits the size
	// of the channel---if too much unsaved Work is received, calls to Add
	// begin to block.
	Limit int
}

func NewFlowControlBuffer(
	params FlowControlParams,
	logger *observability.CoreLogger,
	runHandle *runhandle.RunHandle,
) *FlowControlBuffer {
	return &FlowControlBuffer{
		data:         make(chan FlowControlBufferItem, params.Limit),
		inMemorySize: params.InMemorySize,
		logger:       logger,
		runHandle:    runHandle,
	}
}

// StopOffloading prevents future Add calls from ever discarding incoming data.
//
// This is used if the transaction log file is unreliable
// and we might not be able to reload discarded data.
func (buf *FlowControlBuffer) StopOffloading() {
	buf.offloadingCancelled.Store(true)
}

// Add inserts work into the buffer.
func (buf *FlowControlBuffer) Add(work runwork.MaybeSavedWork) {
	if !work.IsSaved ||
		buf.offloadingCancelled.Load() ||
		(len(buf.data) < buf.inMemorySize && buf.backedUpCount.Load() == 0) {
		buf.push(&FlowControlBufferWork{Work: work.Work})
		return
	}

	if buf.backedUpCount.Add(1) == 1 {
		buf.logger.Info(
			"flowcontrol: backed up, offloading to disk",
			"recordNumber", work.RecordNumber)
		buf.setFlowControlOverflowTelemetry()
	}

	if buf.tryAppendToLastChunk(work) {
		return
	}

	buf.push(&FlowControlBufferSavedChunk{
		InitialOffset: work.SavedOffset,
		InitialNumber: work.RecordNumber,
		Count:         1,
	})
}

// setFlowControlOverflowTelemetry records that the run hit flow control
// in its telemetry.
func (buf *FlowControlBuffer) setFlowControlOverflowTelemetry() {
	// Avoid updating telemetry more than necessary, since each time triggers
	// a config reupload.
	if buf.sentOverflowTelemetry {
		return
	}
	buf.sentOverflowTelemetry = true

	buf.runHandle.UpdateTelemetry(&spb.TelemetryRecord{
		Feature: &spb.Feature{
			FlowControlOverflow: true,
		},
	})
}

// push adds an item to the back of the buffer.
func (buf *FlowControlBuffer) push(workOrSavedChunk FlowControlBufferItem) {
	buf.lastItemMu.Lock()
	buf.lastItem = workOrSavedChunk
	buf.lastItemMu.Unlock()

	buf.data <- workOrSavedChunk
}

// tryAppendToLastChunk tries to add the saved work to the chunk at the back of
// the buffer.
//
// Returns whether the work was added to the buffer.
func (buf *FlowControlBuffer) tryAppendToLastChunk(
	work runwork.MaybeSavedWork,
) bool {
	buf.lastItemMu.Lock()
	defer buf.lastItemMu.Unlock()

	if buf.lastItem == nil {
		return false
	}

	// NOTE: Chunks contain records with consecutive numbers.
	chunk, isSavedChunk := buf.lastItem.(*FlowControlBufferSavedChunk)
	if !isSavedChunk || work.RecordNumber != chunk.InitialNumber+chunk.Count {
		return false
	}

	chunk.Count++
	return true
}

// Close closes the channel, after which Add may not be called.
//
// This may only be called once.
func (buf *FlowControlBuffer) Close() {
	close(buf.data)
}

// Get removes the next item in the buffer and returns it.
//
// If the buffer is empty, this blocks until either it is closed or an item
// is added. Returns nil if the buffer is closed.
func (buf *FlowControlBuffer) Get() FlowControlBufferItem {
	return buf.get(false)
}

// TryGet is like Get, but returns nil if the buffer is empty.
func (buf *FlowControlBuffer) TryGet() FlowControlBufferItem {
	return buf.get(true)
}

func (buf *FlowControlBuffer) get(nonblocking bool) FlowControlBufferItem {
	var item FlowControlBufferItem

	select {
	case item = <-buf.data:
	default:
		totalOffloaded := buf.backedUpCount.Swap(0)
		if totalOffloaded > 0 { // If zero, then we weren't backed up at all.
			buf.logger.Info(
				"flowcontrol: unblocked",
				"totalOffloaded", totalOffloaded)
		}

		if nonblocking {
			return nil
		}

		item = <-buf.data
	}

	buf.lastItemMu.Lock()
	if buf.lastItem == item {
		buf.lastItem = nil
	}
	buf.lastItemMu.Unlock()

	return item
}
