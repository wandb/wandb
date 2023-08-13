package filestream

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestCollectNothing(t *testing.T) {
	input := make(chan processedChunk, 32)
	collector := chunkCollector{input: input}
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
		delayProcess:    30,
		maxItemsPerPush: 100,
	}
	assert.True(t, collector.read())
	collector.readMore()
	offset := FileStreamOffsetMap{}
	assert.Equal(t,
		&FsTransmitData{
			Files: map[string]fsTransmitFileData{
				"wandb-history.jsonl": fsTransmitFileData{
					Offset:  0,
					Content: []string{"line", "line2"},
				},
				"output.log": fsTransmitFileData{
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
	close(input)
	collector := chunkCollector{
		input:           input,
		delayProcess:    30,
		maxItemsPerPush: 100,
	}
	assert.True(t, collector.read())
	collector.readMore()
	offset := FileStreamOffsetMap{}
	assert.Equal(t,
		&FsTransmitData{
			Files: map[string]fsTransmitFileData{
				"wandb-history.jsonl": fsTransmitFileData{
					Offset:  0,
					Content: []string{"line", "line2"},
				},
				"output.log": fsTransmitFileData{
					Offset:  0,
					Content: []string{"line3"},
				},
			},
			Exitcode: &exitcode,
		},
		collector.dump(offset),
	)
}
