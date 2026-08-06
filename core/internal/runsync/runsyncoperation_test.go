package runsync

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// writeRunLog creates an offline run directory in dir with a transaction log
// containing a Run record, and returns the log's path.
func writeRunLog(t *testing.T, dir, runID string) string {
	t.Helper()

	path := newRunLogPath(t, dir, runID)

	writer, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	defer func() { require.NoError(t, writer.Close()) }()

	require.NoError(t, writer.Write(&spb.Record{RecordType: &spb.Record_Run{
		Run: &spb.RunRecord{
			Entity:  "test-entity",
			Project: "test-project",
			RunId:   runID,
			StartTime: timestamppb.New(
				time.Date(2000, 1, 1, 0, 0, 0, 0, time.UTC)),
		},
	}}))

	return path
}

// writeEmptyRunLog is like writeRunLog, but the transaction log contains
// no records, as happens when a run is interrupted right after starting.
func writeEmptyRunLog(t *testing.T, dir, runID string) string {
	t.Helper()

	path := newRunLogPath(t, dir, runID)

	writer, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	require.NoError(t, writer.Close())

	return path
}

// newRunLogPath creates an offline run directory in dir and returns the path
// its transaction log should have.
func newRunLogPath(t *testing.T, dir, runID string) string {
	t.Helper()

	runDir := filepath.Join(dir, "offline-run-"+runID)
	require.NoError(t, os.MkdirAll(runDir, 0o777))

	return filepath.Join(runDir, "run-"+runID+".wandb")
}

// newTestOperation creates an operation with one syncer per transaction log.
func newTestOperation(t *testing.T, paths ...string) *RunSyncOperation {
	t.Helper()

	logger := observabilitytest.NewTestLogger(t)
	readerFactory := &RunReaderFactory{Logger: logger}

	op := &RunSyncOperation{
		printer: observability.NewPrinter(printerBufferSize),
		logger:  logger,
	}

	for _, path := range paths {
		displayPath := ToDisplayPath(path, "")

		op.syncers = append(op.syncers, &RunSyncer{
			path:        path,
			displayPath: displayPath,
			logger:      logger,
			printer:     op.printer,
			runReader: readerFactory.New(
				path,
				displayPath,
				nil,   /*updates*/
				false, /*live*/
				nil,   /*recordParser*/
				nil,   /*runWork*/
			),
		})
	}

	return op
}

func Test_InitAndPlan_SkipsUnreadableRun(t *testing.T) {
	dir := t.TempDir()
	firstPath := writeRunLog(t, dir, "aaa")
	unreadablePath := writeEmptyRunLog(t, dir, "bbb")
	lastPath := writeRunLog(t, dir, "ccc")
	op := newTestOperation(t, firstPath, unreadablePath, lastPath)

	plan, err := op.initAndPlan(context.Background())

	require.NoError(t, err)
	assert.Equal(t,
		map[string][]*RunSyncer{
			"test-entity/test-project/aaa": {op.syncers[0]},
			"test-entity/test-project/ccc": {op.syncers[2]},
		},
		plan)

	messages := op.printer.Read()
	require.Len(t, messages, 1)
	assert.Equal(t, observability.Error, messages[0].Severity)
	assert.Contains(t, messages[0].Content, "offline-run-bbb")
}

func Test_InitAndPlan_AbortsIfCancelled(t *testing.T) {
	dir := t.TempDir()
	op := newTestOperation(t,
		writeRunLog(t, dir, "aaa"),
		writeRunLog(t, dir, "bbb"))
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	plan, err := op.initAndPlan(ctx)

	assert.Nil(t, plan)
	assert.ErrorIs(t, err, context.Canceled)
	assert.Empty(t, op.printer.Read())
}
