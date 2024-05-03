package filestream

import (
	"github.com/wandb/wandb/core/internal/waiting"
)

type chunkMap map[ChunkTypeEnum][]string

var chunkFilename = map[ChunkTypeEnum]string{
	HistoryChunk: HistoryFileName,
	OutputChunk:  OutputFileName,
	EventsChunk:  EventsFileName,
	SummaryChunk: SummaryFileName,
}

type chunkCollector struct {
	// A stream of updates which get batched together.
	input <-chan CollectorStateUpdate

	// Maximum time to wait before finalizing a batch.
	processDelay waiting.Delay

	// Maximum number of chunks to include in a push.
	maxItemsPerPush int

	// **************************************************
	// Internal state
	// **************************************************

	state CollectorState

	// Whether we finished reading the entire input stream.
	isDone bool
}

// CollectAndDump returns the next batch of updates to send to the backend.
//
// Returns nil and false if there are no updates. Otherwise, returns
// the updates and true.
func (cr *chunkCollector) CollectAndDump(
	offsetMap FileStreamOffsetMap,
) (*FsTransmitData, bool) {
	itemsCollected := 0

	maxChunkWait := cr.processDelay.Wait()
	for readMore := true; readMore; {
		select {
		case update, ok := <-cr.input:
			if !ok {
				cr.isDone = true
				readMore = false
				break // out of the select
			}

			update.Apply(&cr.state)
			itemsCollected++

			if itemsCollected >= cr.maxItemsPerPush {
				readMore = false
			}

		case <-maxChunkWait:
			readMore = false
		}
	}

	data, ok := cr.state.Consume(offsetMap, cr.isDone)
	if !ok {
		return nil, false
	} else {
		return data, true
	}
}
