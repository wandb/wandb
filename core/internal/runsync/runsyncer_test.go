package runsync

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/runwork"
)

type resultReader struct {
	work runwork.RunWork
	err  error
}

func (r resultReader) ExtractRunInfo(context.Context) (*RunInfo, error) { return nil, nil }

func (r resultReader) ProcessTransactionLog(
	context.Context,
) error {
	r.work.Close()
	return r.err
}

type resultSender struct{ err error }

func (s resultSender) Do(work <-chan runwork.Work) {
	for range work {
	}
}
func (s resultSender) FileStreamError() error { return s.err }

func TestSyncMarkerRequiresSuccessfulUpload(t *testing.T) {
	failure := errors.New("server rejected history")
	for _, tt := range []struct {
		name               string
		uploadErr, readErr error
		cancelled          bool
	}{
		{name: "success"},
		{name: "upload failed", uploadErr: failure},
		{name: "read failed", readErr: failure},
		{name: "cancelled", cancelled: true},
	} {
		t.Run(tt.name, func(t *testing.T) {
			logger := observability.NewNoOpLogger()
			work := runwork.New(1, logger)
			path := filepath.Join(t.TempDir(), "run.wandb")
			printer := observability.NewPrinter(10)
			rs := &RunSyncer{
				path:        path,
				displayPath: DisplayPath(path),
				logger:      logger,
				printer:     printer,
				runHandle:   runhandle.New(),
				runWork:     work,
				runReader: resultReader{
					work: work,
					err:  tt.readErr,
				},
				sender: resultSender{err: tt.uploadErr},
			}
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			if tt.cancelled {
				cancel()
			}
			err := rs.Sync(ctx)
			if tt.uploadErr != nil || tt.readErr != nil || tt.cancelled {
				require.Error(t, err)
				require.NoFileExists(t, path+".synced")
				for _, message := range printer.Read() {
					require.NotContains(t, message.Content, "Finished syncing")
				}
			} else {
				require.NoError(t, err)
				require.FileExists(t, path+".synced")
			}
			if tt.uploadErr != nil {
				// An upload rejection is not an internal error.
				userText := ToUserText(err)
				require.NotContains(t, userText, "Internal error")
				require.Contains(t, userText, "server rejected history")
				var syncErr *SyncError
				require.ErrorAs(t, err, &syncErr)
				require.Equal(t, tt.uploadErr, syncErr.Err)
			}
		})
	}
}

func TestSyncMarkerWriteFailure(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run.wandb")
	require.NoError(t, os.Mkdir(path+".synced", 0o700))
	rs := &RunSyncer{path: path}
	require.ErrorContains(t, rs.markSynced(), "could not create .synced file")
}
