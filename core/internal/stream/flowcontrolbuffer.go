package stream

import (
	"container/list"
	"sync"

	"github.com/wandb/wandb/core/internal/runwork"
)

// FlowControlBuffer is the FlowControl channel's internal buffer.
//
// This is safe for use by at most two goroutines: one calling Add and
// eventually Close, and another calling Pop.
//
// If all work were saveable, this would essentially be two integers.
// But since some work is not saved to the transaction log (like Requests),
// we represent the buffer as an alternating sequence of saved work chunks
// and non-saved work (stored in memory).
type FlowControlBuffer struct {
	cond     *sync.Cond
	isClosed bool

	// data is a FIFO queue where each element is either
	// *FlowControlBufferWork or *FlowControlBufferSavedChunk.
	data *list.List

	// inMemorySize is the maximum number of saved Work values to keep in memory
	// to avoid having to read the transaction log.
	//
	// If there are fewer than this many items in the list, incoming Work
	// is stored in the list directly regardless of whether it's saved.
	// Otherwise, saved Work values are discarded and later read from the
	// transaction log. Unsaved Work is always kept in memory.
	inMemorySize int

	// limit is the maximum length of the internal list.
	//
	// While the buffer can represent an unlimited amount of saved Work,
	// unsaved Work is saved directly in the list. This limits the size
	// of the list---if too much unsaved Work is received, calls to Add
	// begin to block.
	limit int
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

	// FinalNumber is the record number of the final record in this chunk.
	FinalNumber int64

	// Count is the number of records represented by this chunk.
	Count uint64
}

type FlowControlParams struct {
	InMemorySize int
	Limit        int
}

func NewFlowControlBuffer(params FlowControlParams) *FlowControlBuffer {
	return &FlowControlBuffer{
		cond:         sync.NewCond(&sync.Mutex{}),
		data:         list.New(),
		inMemorySize: params.InMemorySize,
		limit:        params.Limit,
	}
}

// Add inserts work into the buffer.
func (buf *FlowControlBuffer) Add(work runwork.MaybeSavedWork) {
	buf.cond.L.Lock()
	defer buf.cond.L.Unlock()

	if buf.isClosed {
		return
	}

	if !work.IsSaved || buf.data.Len() < buf.inMemorySize {
		buf.push(&FlowControlBufferWork{Work: work.Work})
		return
	}

	// If the back of the list is a chunk of saved work, modify that chunk.
	chunk, isSavedChunk := buf.data.Back().Value.(*FlowControlBufferSavedChunk)
	if isSavedChunk {
		chunk.FinalNumber = work.RecordNumber
		chunk.Count++
		return
	}

	buf.push(&FlowControlBufferSavedChunk{
		InitialOffset: work.SavedOffset,
		InitialNumber: work.RecordNumber,
		FinalNumber:   work.RecordNumber,
		Count:         1,
	})
}

// push appends to data and signals.
func (buf *FlowControlBuffer) push(workOrSavedChunk any) {
	for buf.data.Len() >= buf.limit {
		buf.cond.Wait()
	}

	buf.data.PushBack(workOrSavedChunk)
	buf.cond.Signal()
}

// Close closes the buffer and unblocks Pop, after which Add cannot be called.
func (buf *FlowControlBuffer) Close() {
	buf.cond.L.Lock()
	buf.isClosed = true
	buf.cond.Broadcast()
	buf.cond.L.Unlock()
}

// Pop returns either *FlowControlBufferWork or *FlowControlBufferSavedChunk.
//
// If the buffer is empty, this blocks until either it is closed or an item
// is added. Returns nil if the buffer is closed.
func (buf *FlowControlBuffer) Pop() any {
	buf.cond.L.Lock()
	defer buf.cond.L.Unlock()

	for !buf.isClosed && buf.data.Len() == 0 {
		buf.cond.Wait()
	}

	if buf.isClosed {
		return nil
	}

	// Unblock goroutines waiting in push() due to the data limit.
	buf.cond.Signal()

	return buf.data.Remove(buf.data.Front())
}
