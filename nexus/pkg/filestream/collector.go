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
	input             <-chan fileChunk
	isDone            bool
	heartbeatTime     time.Duration
	delayProcess      time.Duration
	fileChunks        chunkMap
	maxItemsPerPush   int
	itemsCollected    int
	isOverflow        bool
	isTransmitReady   bool
	transmitData      *FsTransmitData
	finalTransmitData *FsTransmitData
}

func (cr *chunkCollector) reset() {
	cr.fileChunks = make(chunkMap)
	cr.itemsCollected = 0
	cr.transmitData = &FsTransmitData{}
	cr.isTransmitReady = false
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

func (cr *chunkCollector) update(chunk fileChunk) {
	// Complete and Exitcode are saved to finalTransmitData because
	// they need to be sent last
	if chunk.Complete != nil || chunk.Exitcode != nil {
		if cr.finalTransmitData != nil {
			cr.finalTransmitData = &FsTransmitData{}
		}
		if chunk.Complete != nil {
			cr.finalTransmitData.Complete = chunk.Complete
		}
		if chunk.Exitcode != nil {
			cr.finalTransmitData.Exitcode = chunk.Exitcode
		}
	} else if chunk.Preempting {
		cr.transmitData.Preempting = chunk.Preempting
	}
}
func (cr *chunkCollector) addFileChunk(chunk fileChunk) {
	if chunk.chunkType != NoneChunk {
		cr.fileChunks[chunk.chunkType] = append(cr.fileChunks[chunk.chunkType], chunk.line)
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
	if len(cr.fileChunks) != 0 {
		files := make(map[string]fsTransmitFileData)
		for chunkType, lines := range cr.fileChunks {
			fname := chunkFilename[chunkType]
			files[fname] = fsTransmitFileData{
				Offset:  offsets[chunkType],
				Content: lines}
			offsets[chunkType] += len(lines)
		}
		cr.transmitData.Files = files
		cr.isTransmitReady = true
	}
	if cr.isDone {
		cr.dumpFinalTransmit()
	}
	if cr.isTransmitReady {
		return cr.transmitData
	}
	return nil
}
