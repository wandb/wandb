package server_test

import (
	"context"
	"errors"
	"io"
	"testing"

	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/server"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/pkg/service"
)

type MockSender struct {
	Records []*service.Record
}

func (s *MockSender) Send(record *service.Record) {
	s.Records = append(s.Records, record)
}

func TestSyncService(t *testing.T) {

	// Helper function to create a SyncService with a mock sender
	createSyncService := func() (*server.SyncService, *MockSender) {
		mockSender := MockSender{}
		syncService := server.NewSyncService(context.Background(),
			server.WithSyncServiceSenderFunc(mockSender.Send),
		)
		syncService.Start()
		return syncService, &mockSender
	}

	// Test syncRun
	t.Run("syncRun", func(t *testing.T) {
		syncService, mockSender := createSyncService()
		run := &service.Record{
			RecordType: &service.Record_Run{
				Run: &service.RunRecord{},
			},
		}
		syncService.SyncRecord(run, nil)
		syncService.Close()
		assert.Equal(t, 2, len(mockSender.Records))
		assert.Equal(t, run, mockSender.Records[0])
		assert.IsType(t, &service.Record_Request{}, mockSender.Records[1].RecordType)
	})

	// Test syncRun with overwrite
	t.Run("syncRun with overwrite", func(t *testing.T) {
		run := &service.Record{
			RecordType: &service.Record_Run{
				Run: &service.RunRecord{},
			},
		}
		overwrite := &service.SyncOverwrite{
			Entity:  "testEntity",
			Project: "testProject",
			RunId:   "testRunId",
		}
		mockSender := MockSender{}
		syncService := server.NewSyncService(context.Background(),
			server.WithSyncServiceSenderFunc(mockSender.Send),
			server.WithSyncServiceOverwrite(overwrite),
		)
		syncService.Start()
		syncService.SyncRecord(run, nil)
		syncService.Close()
		assert.Equal(t, 2, len(mockSender.Records))
		modifiedRun := mockSender.Records[0]
		assert.Equal(t, overwrite.GetEntity(), modifiedRun.GetRun().Entity)
		assert.Equal(t, overwrite.GetProject(), modifiedRun.GetRun().Project)
		assert.Equal(t, overwrite.GetRunId(), modifiedRun.GetRun().RunId)
		assert.IsType(t, &service.Record_Request{}, mockSender.Records[1].RecordType)
	})

	// Test syncOutputRaw
	t.Run("syncOutputRaw", func(t *testing.T) {
		syncService, mockSender := createSyncService()
		record := &service.Record{
			RecordType: &service.Record_OutputRaw{},
		}
		syncService.SyncRecord(record, nil)
		syncService.Close()
		assert.Equal(t, 1, len(mockSender.Records))
		assert.Equal(t, record, mockSender.Records[0])
	})

	// Test syncOutputRaw with skip
	t.Run("syncOutputRaw with skip", func(t *testing.T) {
		skip := &service.SyncSkip{
			OutputRaw: true,
		}
		mockSender := MockSender{}
		syncService := server.NewSyncService(context.Background(),
			server.WithSyncServiceSenderFunc(mockSender.Send),
			server.WithSyncServiceSkip(skip),
		)
		syncService.Start()
		record := &service.Record{
			RecordType: &service.Record_OutputRaw{},
		}
		syncService.SyncRecord(record, nil)
		syncService.Close()
		assert.Equal(t, 0, len(mockSender.Records))
	})

	// Test Flush without callback
	t.Run("Flush without callback", func(t *testing.T) {
		mockSender := MockSender{}
		logger := observability.NewNoOpLogger()
		syncService := server.NewSyncService(context.Background(),
			server.WithSyncServiceSenderFunc(mockSender.Send),
			server.WithSyncServiceLogger(logger),
		)
		syncService.Start()
		syncService.Flush() // Should not panic, but won't send the flushCallback
	})

	// Test Flush with callback
	t.Run("Flush with callback", func(t *testing.T) {
		callbackCalled := false
		flushCallback := func(err error) {
			callbackCalled = true
			assert.NoError(t, err)
		}
		mockSender := MockSender{}
		syncService := server.NewSyncService(context.Background(),
			server.WithSyncServiceSenderFunc(mockSender.Send),
			server.WithSyncServiceFlushCallback(flushCallback),
		)
		syncService.Start()
		syncService.Flush()
		assert.True(t, callbackCalled)
	})

	// Test SyncRecord with error
	t.Run("SyncRecord with error", func(t *testing.T) {
		callbackCalled := false
		flushCallback := func(err error) {
			callbackCalled = true
			assert.Error(t, err)
		}
		mockSender := MockSender{}
		syncService := server.NewSyncService(context.Background(),
			server.WithSyncServiceSenderFunc(mockSender.Send),
			server.WithSyncServiceFlushCallback(flushCallback),
		)
		syncService.Start()
		syncService.SyncRecord(nil, errors.New("test error"))
		syncService.Flush()
		assert.True(t, callbackCalled)
	})

	// Test sync with EOF error
	t.Run("SyncRecord with EOF error", func(t *testing.T) {
		callbackCalled := false
		flushCallback := func(err error) {
			callbackCalled = true
			assert.NoError(t, err)
		}
		mockSender := MockSender{}
		syncService := server.NewSyncService(context.Background(),
			server.WithSyncServiceSenderFunc(mockSender.Send),
			server.WithSyncServiceFlushCallback(flushCallback),
		)
		syncService.Start()
		syncService.SyncRecord(nil, io.EOF)
		syncService.Flush()
		assert.True(t, callbackCalled)
	})

}
