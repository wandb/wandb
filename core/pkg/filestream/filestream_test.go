package filestream_test

import (
	"fmt"

	"github.com/wandb/wandb/core/internal/apitest"
	"github.com/wandb/wandb/core/internal/waitingtest"

	"github.com/wandb/wandb/core/pkg/filestream"
	"github.com/wandb/wandb/core/pkg/observability"

	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/pkg/service"
)

func NewHistoryRecord() *service.Record {
	msg := &service.Record{
		RecordType: &service.Record_History{
			History: &service.HistoryRecord{
				Step: &service.HistoryStep{Num: 0},
				Item: []*service.HistoryItem{
					{Key: "_runtime", ValueJson: fmt.Sprintf("%f", 0.0)},
					{Key: "_step", ValueJson: fmt.Sprintf("%d", 0)},
				}}}}
	return msg
}

func TestStreamRecord_SendsHistory(t *testing.T) {
	num := 10
	fakeClient := apitest.NewFakeClient("test-url")
	fs := filestream.NewFileStream(filestream.FileStreamParams{
		Settings:  &service.Settings{},
		Logger:    observability.NewNoOpLogger(),
		ApiClient: fakeClient,
		// Chunk everything and prevent heartbeats.
		DelayProcess:       waitingtest.NewFakeDelay(),
		HeartbeatStopwatch: waitingtest.NewFakeStopwatch(),
	})

	fs.Start("entity", "project", "run", filestream.FileStreamOffsetMap{})
	fakeClient.SetResponse(&apitest.TestResponse{StatusCode: 200}, nil)
	msg := NewHistoryRecord()
	for i := 0; i < num; i++ {
		fs.StreamRecord(msg)
	}
	fs.Close()

	assert.Len(t, fakeClient.GetRequests(), 1)
}

func TestSendsHeartbeat(t *testing.T) {
	fakeHeartbeat := waitingtest.NewFakeStopwatch()
	fakeClient := apitest.NewFakeClient("test-url")
	fs := filestream.NewFileStream(filestream.FileStreamParams{
		Settings:           &service.Settings{},
		Logger:             observability.NewNoOpLogger(),
		ApiClient:          fakeClient,
		HeartbeatStopwatch: fakeHeartbeat,
	})

	fakeClient.SetResponse(&apitest.TestResponse{StatusCode: 200}, nil)
	fakeHeartbeat.SetDone()
	fs.Start("entity", "project", "run", filestream.FileStreamOffsetMap{})
	// We're relying on a single loop happening in-between. Technically
	// this test is brittle: the code would still be correct if Close()
	// pre-empted Start().
	fs.Close()

	assert.Len(t, fakeClient.GetRequests(), 1)
}
