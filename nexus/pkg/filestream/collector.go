package filestream

import (
	"time"
)

type chunkMap map[ChunkTypeEnum][]string

var chunkFilename = map[ChunkTypeEnum]string{
	HistoryChunk: HistoryFileName,
	OutputChunk:  OutputFileName,
	EventsChunk:  EventsFileName,
	SummaryChunk: SummaryFileName,
}

type chunkCollector struct {
	input             <-chan processedChunk
	isDone            bool
	heartbeatTime     time.Duration
	delayProcess      time.Duration
	fileChunks        chunkMap
	maxItemsPerPush   int
	itemsCollected    int
	isOverflow        bool
	isTransmitReady   bool
	isDirty           bool
	transmitData      *FsTransmitData
	finalTransmitData *FsTransmitData
}

func (cr *chunkCollector) reset() {
	cr.fileChunks = make(chunkMap)
	cr.itemsCollected = 0
	cr.transmitData = &FsTransmitData{}
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
	case <-time.After(cr.heartbeatTime):
	}
	return false
}

func (cr *chunkCollector) delayTime() time.Duration {
	delayTime := cr.delayProcess
	// do not delay for more chunks if we overflowed on last iteration
	if cr.isOverflow {
		delayTime = 0
	}
	cr.isOverflow = false
	return delayTime
}

func (cr *chunkCollector) readMore() {
	// TODO(nexus:beta): add rate limiting
	delayChan := time.After(cr.delayTime())
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
