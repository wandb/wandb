package stream_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/stream"
	"github.com/wandb/wandb/core/internal/transactionlogtest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestWriter_FlushesWhileRunning(t *testing.T) {
	logReader, logWriter := transactionlogtest.ReaderWriter(t)
	writerFactory := &stream.WriterFactory{
		Logger: observabilitytest.NewTestLogger(t),
		Settings: settings.From(&spb.Settings{
			XTransactionLogFlushInterval: &wrapperspb.DoubleValue{Value: 0.01},
		}),
	}
	writer := writerFactory.New(logWriter)
	input := make(chan runwork.Work)
	go writer.Do(input)
	go func() {
		for range writer.Chan() {
		}
	}()
	defer close(input)

	input <- runwork.NoRequest(&runworktest.NoopWork{Value: "1"})

	assert.Eventually(t, func() bool {
		_, err := logReader.Read()
		if err != nil {
			_ = logReader.ResetLastRead()
			return false
		}
		return true
	}, 5*time.Second, 10*time.Millisecond,
		"the record should become readable before the writer is closed")
}
