package filestream

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/waiting"
)

func TestCollectNothing(t *testing.T) {
	input := make(chan CollectorStateUpdate, 32)
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
	input := make(chan CollectorStateUpdate, 32)
	input <- &collectorHistoryUpdate{
		lines: []string{"line"},
	}
	input <- &collectorLogsUpdate{
		line: "line3",
	}
	input <- &collectorPreemptingUpdate{}
	input <- &collectorHistoryUpdate{
		lines: []string{"line2"},
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
	input := make(chan CollectorStateUpdate, 32)
	input <- &collectorHistoryUpdate{
		lines: []string{"line"},
	}
	input <- &collectorExitUpdate{
		exitCode: 2,
	}
	input <- &collectorLogsUpdate{
		line: "line3",
	}
	input <- &collectorHistoryUpdate{
		lines: []string{"line2"},
	}
	collector := chunkCollector{
		input:           input,
		processDelay:    waiting.NewDelay(10 * time.Millisecond),
		maxItemsPerPush: 100,
	}
	close(input)

	data, ok := collector.CollectAndDump(FileStreamOffsetMap{})

	boolTrue := true
	exitcode := int32(2)
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
			Complete: &boolTrue,
			Exitcode: &exitcode,
		},
		data,
	)
}

func TestCollectProcessedChunkUpdate(t *testing.T) {
	input := make(chan CollectorStateUpdate, 32)
	input <- &collectorPreemptingUpdate{}
	collector := chunkCollector{
		input:           input,
		processDelay:    waiting.NewDelay(10 * time.Millisecond),
		maxItemsPerPush: 100,
	}

	data, ok := collector.CollectAndDump(FileStreamOffsetMap{})

	assert.True(t, ok)
	assert.NotNil(t, data)
}
