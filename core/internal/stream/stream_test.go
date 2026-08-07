package stream

import (
	"errors"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestTransactionLog_ReaderFails_ClosesWriter(t *testing.T) {
	realOpenWriter := openTransactionLogWriter
	t.Cleanup(func() {
		openTransactionLogWriter = realOpenWriter
		openTransactionLogReader = transactionlog.OpenReader
	})

	var logWriter *transactionlog.Writer
	openTransactionLogWriter = func(path string) (*transactionlog.Writer, error) {
		w, err := realOpenWriter(path)
		logWriter = w
		return w, err
	}
	openTransactionLogReader = func(
		path string,
		logger *observability.CoreLogger,
	) (*transactionlog.Reader, error) {
		return nil, errors.New("test error")
	}

	stream := &Stream{
		settings: settings.From(&spb.Settings{
			SyncFile: wrapperspb.String(
				filepath.Join(t.TempDir(), "test.wandb")),
		}),
		logger: observabilitytest.NewTestLogger(t),
	}

	_ = stream.maybeSavingToTransactionLog(make(chan runwork.Work))

	require.NotNil(t, logWriter)
	assert.ErrorContains(t, logWriter.Close(), "already closed")
}
