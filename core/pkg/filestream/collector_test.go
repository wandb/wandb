package filestream

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/waiting"
)

func TestCollectNothing(t *testing.T) {
	input := make(chan processedChunk, 32)
	collector := chunkCollector{
		input:           input,
		processDelay:    waiting.NoDelay(),
		maxItemsPerPush: 100,
	}

	data, ok := collector.CollectAndDump(FileStreamOffsetMap{})

	assert.Nil(t, data)
	assert.False(t, ok)
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
		processDelay:    waiting.NewDelay(10 * time.Millisecond),
		maxItemsPerPush: 100,
	}
	data, ok := collector.CollectAndDump(make(FileStreamOffsetMap))

	assert.True(t, ok)
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
		data,
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
		processDelay:    waiting.NewDelay(10 * time.Millisecond),
		maxItemsPerPush: 100,
	}
	close(input)

	data, ok := collector.CollectAndDump(FileStreamOffsetMap{})

	assert.True(t, ok)
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
		data,
	)
}

func TestCollectProcessedChunkUpdate(t *testing.T) {
	input := make(chan processedChunk, 32)
	input <- processedChunk{Preempting: true}
	collector := chunkCollector{
		input:           input,
		processDelay:    waiting.NewDelay(10 * time.Millisecond),
		maxItemsPerPush: 100,
	}

	data, ok := collector.CollectAndDump(FileStreamOffsetMap{})

	assert.True(t, ok)
	assert.NotNil(t, data)
}
