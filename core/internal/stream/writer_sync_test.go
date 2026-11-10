package stream

import (
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/transactionlogtest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// A slow fsync, such as on a network filesystem, must not delay the exit
// record reaching the Sender, which starts the run's finish timeout.
func TestWriter_SlowExitSyncDoesNotDelayExit(t *testing.T) {
	_, logWriter := transactionlogtest.ReaderWriter(t)
	writer := (&WriterFactory{
		Logger:   observabilitytest.NewTestLogger(t),
		Settings: settings.From(&spb.Settings{}),
	}).New(logWriter)

	syncStarted := make(chan struct{})
	release := make(chan struct{})
	writer.syncFile = func() error {
		close(syncStarted)
		<-release
		return nil
	}

	input := make(chan runwork.Work)
	go writer.Do(input)
	defer func() {
		close(release)
		close(input)
		for range writer.Chan() {
		}
	}()

	input <- runwork.Work{WorkImpl: runwork.WorkFromRecord(&spb.Record{
		RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{}},
	})}

	select {
	case saved := <-writer.Chan():
		require.NotNil(t, saved.Work.ToRecord().GetExit())
	case <-time.After(5 * time.Second):
		t.Fatal("exit record was held back by the fsync")
	}

	select {
	case <-syncStarted:
	case <-time.After(5 * time.Second):
		t.Fatal("exit record was not synced")
	}
}

// Closing the log right after the exit record must still fsync it.
func TestWriter_SyncsExitBeforeClosing(t *testing.T) {
	_, logWriter := transactionlogtest.ReaderWriter(t)
	writer := (&WriterFactory{
		Logger:   observabilitytest.NewTestLogger(t),
		Settings: settings.From(&spb.Settings{}),
	}).New(logWriter)

	var syncs atomic.Int32
	writer.syncFile = func() error {
		syncs.Add(1)
		return nil
	}

	input := make(chan runwork.Work, 1)
	input <- runwork.Work{WorkImpl: runwork.WorkFromRecord(&spb.Record{
		RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{}},
	})}
	close(input)

	go writer.Do(input)
	for range writer.Chan() {
	}

	require.EqualValues(t, 1, syncs.Load(), "the exit record was not synced")
}
