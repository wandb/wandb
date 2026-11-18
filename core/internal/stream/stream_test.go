package stream

import (
	"context"
	"errors"
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
		reader, logWriter := transactionlogtest.ReaderWriter(t)
		writer := (&WriterFactory{
			Logger:   observabilitytest.NewTestLogger(t),
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
			logger:  observabilitytest.NewTestLogger(t),
			started: started,
			writer:  writer,
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
		stream.wg.Wait()
	})
}

func TestStream_ExitFlushWithoutWriter(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		started := make(chan struct{})
		close(started)
		stream := &Stream{logger: observabilitytest.NewTestLogger(t), started: started}
		request, responses := runworktest.SimpleRequest(t, "flush")

		stream.HandleRecord(exitFlushRecord(), request)
		stream.HandleRecord(exitFlushRecord(), nil)

		response := <-responses
		require.Equal(t, "transaction log is unavailable", response.GetErrorResponse().GetMessage())
		stream.wg.Wait()
	})
}

func TestStream_ExitFlushCancellationWhileWaitingForWriter(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		writer := &Writer{exitFlushDone: make(chan struct{})}
		started := make(chan struct{})
		close(started)
		stream := &Stream{
			logger:  observabilitytest.NewTestLogger(t),
			started: started,
			writer:  writer,
		}
		ctx, cancel := context.WithCancel(t.Context())
		responses := make(chan *spb.ServerResponse, 1)
		request := runwork.NewRequest("flush", ctx, cancel, responses)

		stream.HandleRecord(exitFlushRecord(), request)
		synctest.Wait()
		cancel()
		stream.wg.Wait()

		select {
		case <-responses:
			t.Fatal("canceled request received a response")
		default:
		}
	})
}

func TestStream_ExitFlushReturnsErrorOnCloseWithoutExit(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		logger := observabilitytest.NewTestLogger(t)
		_, logWriter := transactionlogtest.ReaderWriter(t)
		writer := (&WriterFactory{Logger: logger, Settings: settings.New()}).New(logWriter)
		started := make(chan struct{})
		close(started)
		stream := &Stream{
			logger:  logger,
			started: started,
			writer:  writer,
			runWork: runwork.New(1, logger),
		}
		stream.wg.Add(1)
		go func() {
			defer stream.wg.Done()
			writer.Do(stream.runWork.Chan())
		}()
		request, responses := runworktest.SimpleRequest(t, "flush")

		stream.HandleRecord(exitFlushRecord(), request)
		stream.Close()
		late, lateResponses := runworktest.SimpleRequest(t, "late")
		stream.HandleRecord(exitFlushRecord(), late)

		response := <-responses
		require.Equal(
			t,
			"transaction log closed before an exit record",
			response.GetErrorResponse().GetMessage(),
		)
		require.NotNil(t, (<-lateResponses).GetErrorResponse())
	})
}

func TestStream_ExitFlushReturnsFlushError(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		writer := &Writer{
			exitFlushDone: make(chan struct{}),
			exitFlushErr:  errors.New("flush failed"),
		}
		close(writer.exitFlushDone)
		started := make(chan struct{})
		close(started)
		stream := &Stream{
			logger:  observabilitytest.NewTestLogger(t),
			started: started,
			writer:  writer,
		}
		request, responses := runworktest.SimpleRequest(t, "flush")

		stream.HandleRecord(exitFlushRecord(), request)

		require.Equal(t, "flush failed", (<-responses).GetErrorResponse().GetMessage())
		stream.wg.Wait()
	})
}
