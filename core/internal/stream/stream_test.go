package stream

import (
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// streamWithTransactionLog returns a Stream whose transaction log writer
// writes to a new file, and a reader for that file.
func streamWithTransactionLog(t *testing.T) (*Stream, *transactionlog.Reader) {
	t.Helper()
	logger := observability.NewNoOpLogger()

	path := filepath.Join(t.TempDir(), "run.wandb")
	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	t.Cleanup(func() { _ = w.Close() })

	r, err := transactionlog.OpenReader(path, logger)
	require.NoError(t, err)
	t.Cleanup(r.Close)

	s := &Stream{logger: logger}
	s.transactionWriter.Store((&WriterFactory{Logger: logger}).New(w))
	return s, r
}

func TestFlushTransactionLogs_WritesBufferedRecords(t *testing.T) {
	s, r := streamWithTransactionLog(t)
	require.NoError(t, s.transactionWriter.Load().writer.Write(&spb.Record{Num: 42}))

	// Control: the record is still only in the writer's buffer.
	_, err := r.Read()
	require.Error(t, err)
	require.NoError(t, r.ResetLastRead())

	mux := NewStreamMux()
	require.NoError(t, mux.AddStream("run", s))
	mux.FlushTransactionLogs()

	record, err := r.Read()
	require.NoError(t, err)
	require.EqualValues(t, 42, record.Num)
}

func TestFlushTransactionLogs_SkipsStreamsWithoutLog(t *testing.T) {
	mux := NewStreamMux()
	require.NoError(t, mux.AddStream("run", &Stream{logger: observability.NewNoOpLogger()}))

	mux.FlushTransactionLogs() // must not panic
}
