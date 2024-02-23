package filestream

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestCollectNothing(t *testing.T) {
	input := make(chan processedChunk, 32)
	collector := chunkCollector{
		input:           input,
		heartbeatTime:   2 * time.Second,
		delayProcess:    1 * time.Second,
		maxItemsPerPush: 100,
	}
	assert.False(t, collector.read())
}

func TestCollectSomething(t *testing.T) {
	input := make(chan processedChunk, 32)
	input <- processedChunk{
		fileType: HistoryChunk,
		fileLine: "line",
	}
	input <- processedChunk{
		fileType: OutputChunk,
		fileLine: "line3",
	}
	input <- processedChunk{
		Preempting: true,
	}
	input <- processedChunk{
		fileType: HistoryChunk,
		fileLine: "line2",
	}
	collector := chunkCollector{
		input:           input,
		heartbeatTime:   60 * time.Second,
		delayProcess:    2 * time.Second,
		maxItemsPerPush: 100,
	}
	assert.True(t, collector.read())
	collector.readMore()
	offset := FileStreamOffsetMap{}
	assert.Equal(t,
		&FsTransmitData{
			Files: map[string]fsTransmitFileData{
				"wandb-history.jsonl": {
					Offset:  0,
					Content: []string{"line", "line2"},
				},
				"output.log": {
					Offset:  0,
					Content: []string{"line3"},
				},
			},
			Preempting: true,
		},
		collector.dump(offset),
	)
}

func TestCollectFinal(t *testing.T) {
	input := make(chan processedChunk, 32)
	input <- processedChunk{
		fileType: HistoryChunk,
		fileLine: "line",
	}
	exitcode := int32(2)
	input <- processedChunk{
		Exitcode: &exitcode,
	}
	input <- processedChunk{
		fileType: OutputChunk,
		fileLine: "line3",
	}
	input <- processedChunk{
		fileType: HistoryChunk,
		fileLine: "line2",
	}
	collector := chunkCollector{
		input:           input,
		heartbeatTime:   60 * time.Second,
		delayProcess:    30 * time.Second,
		maxItemsPerPush: 100,
	}
	close(input)
	assert.True(t, collector.read())
	collector.readMore()
	offset := FileStreamOffsetMap{}
	assert.Equal(t,
		&FsTransmitData{
			Files: map[string]fsTransmitFileData{
				"wandb-history.jsonl": {
					Offset:  0,
					Content: []string{"line", "line2"},
				},
				"output.log": {
					Offset:  0,
					Content: []string{"line3"},
				},
			},
			Exitcode: &exitcode,
		},
		collector.dump(offset),
	)
}

func TestIsDirtyAfterAddingChunk(t *testing.T) {
	input := make(chan processedChunk, 32)
	input <- processedChunk{
		fileType: HistoryChunk,
		fileLine: "line",
	}
	collector := chunkCollector{
		input:           input,
		heartbeatTime:   60 * time.Second,
		delayProcess:    2 * time.Second,
		maxItemsPerPush: 100,
	}
	collector.read()
	assert.True(t, collector.isDirty)
}

func TestIsDirtyAfterProcessedChunkUpdate(t *testing.T) {
	input := make(chan processedChunk, 32)
	input <- processedChunk{
		Preempting: true,
	}
	collector := chunkCollector{
		input:           input,
		heartbeatTime:   60 * time.Second,
		delayProcess:    2 * time.Second,
		maxItemsPerPush: 100,
	}
	collector.read()
	assert.True(t, collector.isDirty)
}

func TestIsDirtyResetAfterDump(t *testing.T) {
	input := make(chan processedChunk, 32)
	input <- processedChunk{
		fileType: HistoryChunk,
		fileLine: "line",
	}
	collector := chunkCollector{
		input:           input,
		heartbeatTime:   60 * time.Second,
		delayProcess:    2 * time.Second,
		maxItemsPerPush: 100,
	}
	collector.read()
	offset := FileStreamOffsetMap{}
	collector.dump(offset)
	assert.False(t, collector.isDirty)
}
