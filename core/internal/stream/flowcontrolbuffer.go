package stream

import (
	"sync"

	"github.com/wandb/wandb/core/internal/runwork"
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
	// data is a channel where each element is either
	// *FlowControlBufferWork or *FlowControlBufferSavedChunk.
	data chan any

	// lastItem is the item at the back of data or nil.
	lastItem any

	// lastItemMu guarantees that we don't modify lastItem after returning
	// it from Get.
	lastItemMu sync.Mutex

	// inMemorySize is FlowControlParams.InMemorySize.
	inMemorySize int
}

type FlowControlBufferWork struct {
	runwork.Work
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

type FlowControlParams struct {
	// InMemorySize is the maximum number of saved Work values to keep in memory
	// to avoid having to read the transaction log.
	//
	// If there are fewer than this many items in the list, incoming Work
	// is stored in the list directly regardless of whether it's saved.
	// Otherwise, saved Work values are discarded and later read from the
	// transaction log. Unsaved Work is always kept in memory.
	InMemorySize int

	// Limit is the maximum length of the internal list.
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

func NewFlowControlBuffer(params FlowControlParams) *FlowControlBuffer {
	return &FlowControlBuffer{
		data:         make(chan any, params.Limit),
		inMemorySize: params.InMemorySize,
	}
}

// Add inserts work into the buffer.
func (buf *FlowControlBuffer) Add(work runwork.MaybeSavedWork) {
	if !work.IsSaved || len(buf.data) < buf.inMemorySize {
		buf.push(&FlowControlBufferWork{Work: work.Work})
		return
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

// push adds an item to the back of the buffer.
func (buf *FlowControlBuffer) push(workOrSavedChunk any) {
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
// The result is either *FlowControlBufferWork or *FlowControlBufferSavedChunk.
//
// If the buffer is empty, this blocks until either it is closed or an item
// is added. Returns nil if the buffer is closed.
func (buf *FlowControlBuffer) Get() any {
	item := <-buf.data

	buf.lastItemMu.Lock()
	if buf.lastItem == item {
		buf.lastItem = nil
	}
	buf.lastItemMu.Unlock()

	return item
}
