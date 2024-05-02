package filestream

import (
	"testing"

	"github.com/segmentio/encoding/json"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/apitest"
	"github.com/wandb/wandb/core/internal/waitingtest"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

func testSendAndReceive(t *testing.T, chunks []processedChunk, fsd FsTransmitData) {
	fakeClient := apitest.NewFakeClient("test-url")
	fs := NewFileStream(FileStreamParams{
		Settings:  &service.Settings{},
		Logger:    observability.NewNoOpLogger(),
		ApiClient: fakeClient,
		// Chunk everything and prevent heartbeats.
		DelayProcess:       waitingtest.NewFakeDelay(),
		HeartbeatStopwatch: waitingtest.NewFakeStopwatch(),
	}).(*fileStream)

	fakeClient.SetResponse(&apitest.TestResponse{StatusCode: 200}, nil)
	fs.Start("entity", "project", "run", FileStreamOffsetMap{})
	for _, d := range chunks {
		fs.transmitChan <- d
	}
	fs.Close()

	requests := fakeClient.GetRequests()
	assert.Len(t, requests, 1)

	var actualFSD FsTransmitData
	require.NoError(t, json.Unmarshal(requests[0].Body, &actualFSD))
	assert.Equal(t, fsd, actualFSD)
}

func TestSendChunks(t *testing.T) {
	send := processedChunk{
		fileType: HistoryChunk,
		fileLine: "this is a line",
	}
	expect := FsTransmitData{
		Files: map[string]fsTransmitFileData{
			"wandb-history.jsonl": {
				Offset:  0,
				Content: []string{"this is a line"},
			},
		},
	}
	testSendAndReceive(t, []processedChunk{send}, expect)
}
