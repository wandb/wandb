package stream

import (
	"context"
	"testing"
	"testing/synctest"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/transactionlogtest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func exitFlushRecord() *spb.Record {
	return &spb.Record{RecordType: &spb.Record_Request{Request: &spb.Request{
		RequestType: &spb.Request_WaitForRunExitFlush{
			WaitForRunExitFlush: &spb.WaitForRunExitFlushRequest{},
		},
	}}}
}

func TestStream_ExitFlushNotifiesMultipleAndLateRequests(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		logger := observabilitytest.NewTestLogger(t)
		reader, logWriter := transactionlogtest.ReaderWriter(t)
		writer := (&WriterFactory{
			Logger:   logger,
			Settings: settings.New(),
		}).New(logWriter)
		input := make(chan runwork.Work)
		go writer.Do(input)
		defer func() {
			close(input)
			for range writer.Chan() {
			}
		}()
		started := make(chan struct{})
		close(started)
		stream := &Stream{
			logger:              logger,
			started:             started,
			transactionLogReady: writer.exitFlushDone,
			runWork:             runwork.New(1, logger),
		}
		first, firstResponses := runworktest.SimpleRequest(t, "first")
		second, secondResponses := runworktest.SimpleRequest(t, "second")

		stream.HandleRecord(exitFlushRecord(), first)
		stream.HandleRecord(exitFlushRecord(), second)
		synctest.Wait()
		select {
		case <-firstResponses:
			t.Fatal("response arrived before exit")
		default:
		}
		select {
		case <-secondResponses:
			t.Fatal("response arrived before exit")
		default:
		}
		input <- runwork.NoRequest(runwork.WorkFromRecord(&spb.Record{
			RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{ExitCode: 42}},
		}))
		synctest.Wait() // The writer is blocked forwarding exit.
		late, lateResponses := runworktest.SimpleRequest(t, "late")
		stream.HandleRecord(exitFlushRecord(), late)

		for _, responses := range []<-chan *spb.ServerResponse{firstResponses, secondResponses, lateResponses} {
			response := <-responses
			require.NotNil(
				t,
				response.GetResultCommunicate().GetResponse().GetWaitForRunExitFlushResponse(),
			)
		}
		record, err := reader.Read()
		require.NoError(t, err)
		require.EqualValues(t, 42, record.GetExit().GetExitCode())
		synctest.Wait()
	})
}

func TestStream_ExitFlushWithoutWriter(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		started := make(chan struct{})
		close(started)
		logger := observabilitytest.NewTestLogger(t)
		stream := &Stream{logger: logger, started: started, runWork: runwork.New(1, logger)}
		request, responses := runworktest.SimpleRequest(t, "flush")

		stream.HandleRecord(exitFlushRecord(), request)
		stream.HandleRecord(exitFlushRecord(), nil)

		response := <-responses
		require.Equal(t, "No response.", response.GetErrorResponse().GetMessage())
		synctest.Wait()
	})
}

func TestStream_ExitFlushCancellationWhileWaitingForWriter(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		logger := observabilitytest.NewTestLogger(t)
		writer := &Writer{exitFlushDone: make(chan struct{})}
		started := make(chan struct{})
		close(started)
		stream := &Stream{
			logger:              logger,
			started:             started,
			transactionLogReady: writer.exitFlushDone,
			runWork:             runwork.New(1, logger),
		}
		ctx, cancel := context.WithCancel(t.Context())
		responses := make(chan *spb.ServerResponse, 1)
		request := runwork.NewRequest("flush", ctx, cancel, responses)

		stream.HandleRecord(exitFlushRecord(), request)
		synctest.Wait()
		cancel()
		synctest.Wait()

		select {
		case <-responses:
			t.Fatal("canceled request received a response")
		default:
		}
	})
}

func TestStream_ExitFlushRespondsWhenWriterStopsWithoutExit(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		logger := observabilitytest.NewTestLogger(t)
		_, logWriter := transactionlogtest.ReaderWriter(t)
		writer := (&WriterFactory{Logger: logger, Settings: settings.New()}).New(logWriter)
		started := make(chan struct{})
		close(started)
		stream := &Stream{
			logger:              logger,
			started:             started,
			transactionLogReady: writer.exitFlushDone,
			runWork:             runwork.New(1, logger),
		}
		input := make(chan runwork.Work)
		stream.wg.Add(1)
		go func() {
			defer stream.wg.Done()
			writer.Do(input)
		}()
		request, responses := runworktest.SimpleRequest(t, "flush")

		stream.HandleRecord(exitFlushRecord(), request)
		synctest.Wait()
		close(input)
		response := <-responses
		require.NotNil(
			t,
			response.GetResultCommunicate().GetResponse().GetWaitForRunExitFlushResponse(),
		)
		stream.Close()
	})
}
