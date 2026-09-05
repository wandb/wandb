package stream_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/stream"
	"github.com/wandb/wandb/core/internal/transactionlogtest"
)

func TestWriter_FlushesWhileRunning(t *testing.T) {
	logReader, logWriter := transactionlogtest.ReaderWriter(t)
	writerFactory := &stream.WriterFactory{
		Logger:   observabilitytest.NewTestLogger(t),
		Settings: settings.New(),
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
	}, 5*time.Second, 50*time.Millisecond,
		"the record should become readable before the writer is closed")
}
