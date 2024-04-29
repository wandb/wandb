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
	input <-chan processedChunk

	// Maximum time to wait for an input.
	heartbeatDelay waiting.Delay

	// Maximum time to wait before finalizing a batch.
	processDelay waiting.Delay

	// Maximum number of chunks to include in a push.
	maxItemsPerPush int

	// **************************************************
	// Internal state
	// **************************************************

	// The next batch of updates to send.
	transmitData *FsTransmitData
	fileChunks   chunkMap

	// Whether we have something for the next batch.
	isTransmitReady bool

	// Whether we gathered at least one chunk.
	isDirty bool

	// Number of chunks collected for the next batch.
	itemsCollected int

	// Whether itemsCollected >= maxItemsPerPush in the last batch.
	//
	// When this is true, we skip waiting in the next batch.
	isOverflow bool

	// Whether we finished reading the entire input stream.
	isDone bool

	// The Complete and ExitCode status for the final transmission.
	finalTransmitData *FsTransmitData
}

// CollectAndDump returns the next batch of updates to send to the backend.
//
// Returns nil and false if there are no updates. Otherwise, returns
// the updates and true.
func (cr *chunkCollector) CollectAndDump(
	offsetMap FileStreamOffsetMap,
) (*FsTransmitData, bool) {
	shouldReadMore := cr.read()
	if shouldReadMore {
		cr.readMore()
	}
	data := cr.dump(offsetMap)

	if data == nil {
		return nil, false
	} else {
		return data, true
	}
}

func (cr *chunkCollector) reset() {
	cr.transmitData = &FsTransmitData{}
	cr.fileChunks = make(chunkMap)
	cr.itemsCollected = 0
	cr.isTransmitReady = false
	cr.isDirty = false
}

func (cr *chunkCollector) read() bool {
	cr.reset()

	select {
	case chunk, ok := <-cr.input:
		if !ok {
			cr.isDone = true
			break
		}
		cr.addFileChunk(chunk)
		return true
	case <-cr.heartbeatDelay.Wait():
	}
	return false
}

func (cr *chunkCollector) delayTime() waiting.Delay {
	delay := cr.processDelay

	// do not delay for more chunks if we overflowed on last iteration
	if cr.isOverflow {
		delay = waiting.NoDelay()
	}
	cr.isOverflow = false

	return delay
}

func (cr *chunkCollector) readMore() {
	// TODO(core:beta): add rate limiting
	delayChan := cr.delayTime().Wait()

	for {
		select {
		case chunk, ok := <-cr.input:
			if !ok {
				cr.isDone = true
				return
			}
			cr.addFileChunk(chunk)
			if cr.itemsCollected >= cr.maxItemsPerPush {
				cr.isOverflow = true
				return
			}
		case <-delayChan:
			return
		}
	}
}

func (cr *chunkCollector) update(chunk processedChunk) {
	// Complete and Exitcode are saved to finalTransmitData because
	// they need to be sent last
	switch {
	case chunk.Complete != nil || chunk.Exitcode != nil:
		if cr.finalTransmitData == nil {
			cr.finalTransmitData = &FsTransmitData{}
		}
		if chunk.Complete != nil {
			cr.finalTransmitData.Complete = chunk.Complete
		}
		if chunk.Exitcode != nil {
			cr.finalTransmitData.Exitcode = chunk.Exitcode
		}

	case chunk.Preempting:
		cr.transmitData.Preempting = chunk.Preempting
		cr.isDirty = true

	case chunk.Uploaded != nil:
		cr.transmitData.Uploaded = chunk.Uploaded
		cr.isDirty = true
	}
}

func (cr *chunkCollector) addFileChunk(chunk processedChunk) {
	if chunk.fileType != NoneChunk {
		cr.fileChunks[chunk.fileType] = append(cr.fileChunks[chunk.fileType], chunk.fileLine)
		cr.isDirty = true
	} else {
		cr.update(chunk)
	}
	cr.itemsCollected += 1
}

func (cr *chunkCollector) dumpFinalTransmit() {
	if cr.finalTransmitData == nil {
		return
	}
	cr.isTransmitReady = true
	if cr.finalTransmitData.Complete != nil {
		cr.transmitData.Complete = cr.finalTransmitData.Complete
	}
	if cr.finalTransmitData.Exitcode != nil {
		cr.transmitData.Exitcode = cr.finalTransmitData.Exitcode
	}
}

func (cr *chunkCollector) dump(offsets FileStreamOffsetMap) *FsTransmitData {
	if cr.isDirty {
		files := make(map[string]fsTransmitFileData)
		for fileType, lines := range cr.fileChunks {
			fname := chunkFilename[fileType]
			files[fname] = fsTransmitFileData{
				Offset:  offsets[fileType],
				Content: lines}
			offsets[fileType] += len(lines)
		}
		cr.transmitData.Files = files
		cr.isTransmitReady = true
		cr.isDirty = false
	}
	if cr.isDone {
		cr.dumpFinalTransmit()
	}
	if cr.isTransmitReady {
		return cr.transmitData
	}
	return nil
}
