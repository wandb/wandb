package stream_test

import (
	"testing"
	"testing/synctest"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/stream"
	"github.com/wandb/wandb/core/internal/transactionlogtest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

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
		writer := (&stream.WriterFactory{
			Logger:   observabilitytest.NewTestLogger(t),
			Settings: settings.From(&spb.Settings{}),
		}).New(logWriter)
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
