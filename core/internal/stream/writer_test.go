package stream_test

import (
	"io"
	"testing"
	"testing/synctest"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/stream"
	"github.com/wandb/wandb/core/internal/transactionlog"
	"github.com/wandb/wandb/core/internal/transactionlogtest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func makeExitFlushWork(t *testing.T) (runwork.Work, <-chan *spb.ServerResponse) {
	t.Helper()

	request, responses := runworktest.SimpleRequest(t, "flush")
	return runwork.Work{
		WorkImpl: runwork.WorkFromRecord(&spb.Record{
			RecordType: &spb.Record_Request{Request: &spb.Request{
				RequestType: &spb.Request_WaitForRunExitFlush{
					WaitForRunExitFlush: &spb.WaitForRunExitFlushRequest{},
				},
			}},
		}),
		Request: request,
	}, responses
}

func startTestWriter(t *testing.T) (*transactionlog.Reader, *stream.Writer, chan runwork.Work) {
	t.Helper()

	logReader, logWriter := transactionlogtest.ReaderWriter(t)
	writerFactory := &stream.WriterFactory{
		Logger:   observabilitytest.NewTestLogger(t),
		Settings: settings.New(),
	}
	writer := writerFactory.New(logWriter)
	input := make(chan runwork.Work)
	go writer.Do(input)
	return logReader, writer, input
}

func TestWriter_FlushesPeriodically(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		logReader, logWriter := transactionlogtest.ReaderWriter(t)
		require.NoError(t, logWriter.Write(&spb.Record{Num: 1}))

		writerFactory := &stream.WriterFactory{
			Logger: observabilitytest.NewTestLogger(t),
			Settings: settings.From(&spb.Settings{
				XTransactionLogFlushInterval: &wrapperspb.DoubleValue{Value: 3600},
			}),
		}
		writer := writerFactory.New(logWriter)
		input := make(chan runwork.Work)
		defer close(input)
		go writer.Do(input)
		synctest.Wait()

		_, err := logReader.Read()
		require.Error(t, err, "the record should not be readable before a flush")
		require.NoError(t, logReader.ResetLastRead())

		synctest.Sleep(time.Hour)

		record, err := logReader.Read()
		require.NoError(t, err)
		assert.EqualValues(t, 1, record.Num)
	})
}

func TestWriter_FlushesExitBeforeForwarding(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		logReader, logWriter := transactionlogtest.ReaderWriter(t)
		writerFactory := &stream.WriterFactory{
			Logger:   observabilitytest.NewTestLogger(t),
			Settings: settings.New(),
		}
		writer := writerFactory.New(logWriter)
		input := make(chan runwork.Work)
		go writer.Do(input)
		defer func() {
			close(input)
			for range writer.Chan() {
			}
		}()
		input <- runwork.NoRequest(runwork.WorkFromRecord(&spb.Record{}))
		<-writer.Chan()
		_, err := logReader.Read()
		require.Error(t, err, "the record should not be readable before a flush")
		require.NoError(t, logReader.ResetLastRead())

		input <- runwork.NoRequest(runwork.WorkFromRecord(&spb.Record{
			RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{ExitCode: 42}},
		}))
		synctest.Wait() // The writer is blocked forwarding the exit to the sender.

		record, err := logReader.Read()
		require.NoError(t, err)
		assert.EqualValues(t, 1, record.Num)
		record, err = logReader.Read()
		require.NoError(t, err)
		require.NotNil(t, record.GetExit())
		assert.EqualValues(t, 42, record.GetExit().GetExitCode())
	})
}

func TestWriter_RespondsToExitFlushRequest(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		logReader, writer, input := startTestWriter(t)
		defer func() {
			close(input)
			for range writer.Chan() {
			}
		}()
		work, responses := makeExitFlushWork(t)

		input <- work
		synctest.Wait()
		select {
		case <-responses:
			t.Fatal("request responded before exit")
		default:
		}
		input <- runwork.NoRequest(runwork.WorkFromRecord(&spb.Record{
			RecordType: &spb.Record_Output{Output: &spb.OutputRecord{Line: "data"}},
		}))
		<-writer.Chan()
		input <- runwork.NoRequest(runwork.WorkFromRecord(makeExitRecord()))
		synctest.Wait() // The writer is blocked forwarding exit to the sender.

		response := <-responses
		require.NotNil(t, response.GetResultCommunicate().GetResponse().GetWaitForRunExitFlushResponse())
		first, err := logReader.Read()
		require.NoError(t, err)
		assert.Equal(t, "data", first.GetOutput().GetLine())
		exit, err := logReader.Read()
		require.NoError(t, err)
		require.NotNil(t, exit.GetExit())
	})
}

func TestWriter_RespondsToExitFlushAfterPreviousWriteFailure(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		logReader, writer, input := startTestWriter(t)
		defer func() {
			close(input)
			for range writer.Chan() {
			}
		}()
		work, responses := makeExitFlushWork(t)

		input <- work
		synctest.Wait()
		select {
		case <-responses:
			t.Fatal("request responded before exit")
		default:
		}
		input <- runwork.NoRequest(runwork.WorkFromRecord(&spb.Record{
			Uuid:       "\xff",
			RecordType: &spb.Record_Output{Output: &spb.OutputRecord{Line: "data"}},
		}))
		<-writer.Chan()
		input <- runwork.NoRequest(runwork.WorkFromRecord(makeExitRecord()))
		synctest.Wait() // The writer is blocked forwarding exit to the sender.

		response := <-responses
		require.NotNil(t, response.GetResultCommunicate().GetResponse().GetWaitForRunExitFlushResponse())
		exit, err := logReader.Read()
		require.NoError(t, err)
		require.NotNil(t, exit.GetExit())
	})
}

func TestWriter_RespondsToExitFlushAfterExitWriteFailure(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		logReader, writer, input := startTestWriter(t)
		defer func() {
			close(input)
			for range writer.Chan() {
			}
		}()
		work, responses := makeExitFlushWork(t)

		input <- work
		synctest.Wait()
		select {
		case <-responses:
			t.Fatal("request responded before exit")
		default:
		}
		input <- runwork.NoRequest(runwork.WorkFromRecord(&spb.Record{
			RecordType: &spb.Record_Output{Output: &spb.OutputRecord{Line: "data"}},
		}))
		<-writer.Chan()
		exitRecord := makeExitRecord()
		exitRecord.Uuid = "\xff"
		input <- runwork.NoRequest(runwork.WorkFromRecord(exitRecord))
		synctest.Wait() // The writer is blocked forwarding exit to the sender.

		response := <-responses
		require.NotNil(t, response.GetResultCommunicate().GetResponse().GetWaitForRunExitFlushResponse())
		first, err := logReader.Read()
		require.NoError(t, err)
		assert.Equal(t, "data", first.GetOutput().GetLine())
		_, err = logReader.Read()
		require.ErrorIs(t, err, io.EOF)
	})
}

func TestWriter_RejectsExitFlushWhenClosedWithoutExit(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		_, logWriter := transactionlogtest.ReaderWriter(t)
		writerFactory := &stream.WriterFactory{
			Logger:   observabilitytest.NewTestLogger(t),
			Settings: settings.New(),
		}
		writer := writerFactory.New(logWriter)
		input := make(chan runwork.Work)
		work, responses := makeExitFlushWork(t)
		go writer.Do(input)

		input <- work
		close(input)

		response := <-responses
		require.NotNil(t, response.GetErrorResponse())
		for range writer.Chan() {
		}
	})
}
