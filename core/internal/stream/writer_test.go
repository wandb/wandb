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

func TestWriter_SyncsOnExitRecord(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		logReader, logWriter := transactionlogtest.ReaderWriter(t)

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
		go func() {
			for range writer.Chan() {
			}
		}()

		input <- runwork.Work{WorkImpl: runwork.WorkFromRecord(&spb.Record{
			RecordType: &spb.Record_History{History: &spb.HistoryRecord{}},
		})}
		synctest.Wait()
		_, err := logReader.Read()
		require.Error(t, err, "control: a history record waits for a flush")
		require.NoError(t, logReader.ResetLastRead())

		input <- runwork.Work{WorkImpl: runwork.WorkFromRecord(&spb.Record{
			RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{ExitCode: 7}},
		})}
		synctest.Wait()

		history, err := logReader.Read()
		require.NoError(t, err)
		assert.NotNil(t, history.GetHistory())
		exit, err := logReader.Read()
		require.NoError(t, err)
		assert.EqualValues(t, 7, exit.GetExit().GetExitCode())
	})
}
