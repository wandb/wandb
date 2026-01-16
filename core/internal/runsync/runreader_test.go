package runsync_test

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runsync"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/streamtest"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type testFixtures struct {
	RunReader *runsync.RunReader

	TransactionLog   string
	FakeRunWork      *runworktest.FakeRunWork
	MockRecordParser *streamtest.MockRecordParser
}

// setup creates a RunReader and test objects.
func setup(t *testing.T) testFixtures {
	t.Helper()

	transactionLog := filepath.Join(t.TempDir(), "test-run.wandb")

	fakeRunWork := runworktest.New()
	fakeRunWork.SetDone() // so that Close() doesn't block

	mockCtrl := gomock.NewController(t)
	mockRecordParser := streamtest.NewMockRecordParser(mockCtrl)

	factory := runsync.RunReaderFactory{
		Logger: observabilitytest.NewTestLogger(t),
	}

	return testFixtures{
		RunReader: factory.New(
			transactionLog,
			runsync.ToDisplayPath(transactionLog, ""),
			nil,
			false,
			mockRecordParser,
			fakeRunWork,
		),

		TransactionLog:   transactionLog,
		FakeRunWork:      fakeRunWork,
		MockRecordParser: mockRecordParser,
	}
}

// wandbFileWithRecords writes a transaction log with the given records.
func wandbFileWithRecords(
	t *testing.T,
	path string,
	records ...*spb.Record,
) {
	t.Helper()

	store, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	defer func() { require.NoError(t, store.Close()) }()

	for _, rec := range records {
		err := store.Write(rec)
		require.NoError(t, err)
	}
}

// testWork is a fake runwork.Work for tests.
type testWork struct {
	runwork.SimpleScheduleMixin
	runwork.AlwaysAcceptMixin
	runwork.NoopProcessMixin

	ID int // for equality assertions in tests
}

var _ runwork.Work = &testWork{}

// ToRecord implements Work.ToRecord.
func (w *testWork) ToRecord() *spb.Record { return nil }

// DebugInfo implements Work.DebugInfo.
func (w *testWork) DebugInfo() string {
	return "scheduleCountingWork"
}

// isRecordWithNumber matches a Record with a given Num.
func isRecordWithNumber(n int64) gomock.Matcher {
	return gomock.Cond(
		func(val any) bool {
			return val.(*spb.Record).Num == n
		},
	)
}

// isRunStartRequest matches a Record that is a RunStartRequest.
func isRunStartRequest() gomock.Matcher {
	return gomock.Cond(
		func(val any) bool {
			return val.(*spb.Record).GetRequest().GetRunStart() != nil
		},
	)
}

// exitRecord returns an Exit record with the given exit code.
func exitRecord(code int32) *spb.Record {
	return &spb.Record{
		RecordType: &spb.Record_Exit{
			Exit: &spb.RunExitRecord{
				ExitCode: code,
			},
		},
	}
}

// isExitRecord matches an Exit record with the given exit code.
func isExitRecord(code int32) gomock.Matcher {
	return gomock.Cond(
		func(val any) bool {
			return val.(*spb.Record).GetExit().ExitCode == code
		},
	)
}

func Test_Extract_FindsRunRecord(t *testing.T) {
	x := setup(t)
	startTime := time.Date(2000, 1, 1, 0, 0, 0, 0, time.UTC)
	wandbFileWithRecords(t,
		x.TransactionLog,
		&spb.Record{RecordType: &spb.Record_Run{
			Run: &spb.RunRecord{
				Entity:    "test entity",
				Project:   "test project",
				RunId:     "test run ID",
				StartTime: timestamppb.New(startTime),
			},
		}})

	runInfo, err := x.RunReader.ExtractRunInfo(context.Background())
	require.NoError(t, err)

	assert.Equal(t, &runsync.RunInfo{
		Entity:    "test entity",
		Project:   "test project",
		RunID:     "test run ID",
		StartTime: startTime,
	}, runInfo)
}

func Test_Extract_ErrorIfNoRunRecord(t *testing.T) {
	x := setup(t)
	wandbFileWithRecords(t, x.TransactionLog)

	runInfo, err := x.RunReader.ExtractRunInfo(context.Background())

	assert.Nil(t, runInfo)
	assert.ErrorContains(t, err, "didn't find run info")
}

func Test_Extract_ErrorIfNoFile(t *testing.T) {
	x := setup(t)

	runInfo, err := x.RunReader.ExtractRunInfo(context.Background())

	assert.Nil(t, runInfo)
	assert.ErrorContains(t, err, "failed to open reader")
}

func Test_TurnsAllRecordsIntoWork(t *testing.T) {
	x := setup(t)
	wandbFileWithRecords(t,
		x.TransactionLog,
		&spb.Record{Num: 1},
		&spb.Record{Num: 2},
		exitRecord(0),
	)
	work1 := &testWork{ID: 1}
	work2 := &testWork{ID: 2}
	exitWork := &testWork{ID: 3}
	gomock.InOrder(
		x.MockRecordParser.EXPECT().Parse(isRecordWithNumber(1)).Return(work1),
		x.MockRecordParser.EXPECT().Parse(isRecordWithNumber(2)).Return(work2),
		x.MockRecordParser.EXPECT().Parse(isExitRecord(0)).Return(exitWork),
	)

	err := x.RunReader.ProcessTransactionLog(context.Background())
	require.NoError(t, err)

	assert.Equal(t,
		[]runwork.Work{work1, work2, exitWork},
		x.FakeRunWork.AllWork())
}

func Test_CreatesExitRecordIfNotSeen(t *testing.T) {
	x := setup(t)
	wandbFileWithRecords(t, x.TransactionLog, &spb.Record{Num: 1})
	work1 := &testWork{ID: 1}
	exitWork := &testWork{ID: 2}
	gomock.InOrder(
		x.MockRecordParser.EXPECT().Parse(isRecordWithNumber(1)).Return(work1),
		x.MockRecordParser.EXPECT().Parse(isExitRecord(1)).Return(exitWork),
	)

	err := x.RunReader.ProcessTransactionLog(context.Background())
	require.NoError(t, err)

	assert.Equal(t,
		[]runwork.Work{work1, exitWork},
		x.FakeRunWork.AllWork())
}

func Test_CreatesRunStartRequest(t *testing.T) {
	x := setup(t)
	wandbFileWithRecords(t,
		x.TransactionLog,
		&spb.Record{
			Num:        1,
			RecordType: &spb.Record_Run{Run: &spb.RunRecord{}},
		},
	)
	runWork := &testWork{ID: 1}
	runStartWork := &testWork{ID: 2}
	exitWork := &testWork{ID: 3}
	gomock.InOrder(
		x.MockRecordParser.EXPECT().Parse(isRecordWithNumber(1)).Return(runWork),
		x.MockRecordParser.EXPECT().Parse(isRunStartRequest()).Return(runStartWork),
		x.MockRecordParser.EXPECT().Parse(isExitRecord(1)).Return(exitWork),
	)

	err := x.RunReader.ProcessTransactionLog(context.Background())
	require.NoError(t, err)

	assert.Equal(t,
		[]runwork.Work{runWork, runStartWork, exitWork},
		x.FakeRunWork.AllWork())
}

func Test_FileNotFoundError(t *testing.T) {
	x := setup(t)
	x.MockRecordParser.EXPECT().Parse(isExitRecord(1)).Return(&testWork{})

	err := x.RunReader.ProcessTransactionLog(context.Background())

	var syncErr *runsync.SyncError
	require.ErrorAs(t, err, &syncErr)
	assert.ErrorIs(t, syncErr.Err, os.ErrNotExist)
	assert.Equal(t,
		fmt.Sprintf("File does not exist: %s", x.TransactionLog),
		syncErr.UserText,
	)
}

func Test_FilePermissionError(t *testing.T) {
	x := setup(t)
	wandbFileWithRecords(t, x.TransactionLog)
	err := os.Chmod(x.TransactionLog, 0o200) // write-only
	require.NoError(t, err)
	x.MockRecordParser.EXPECT().Parse(isExitRecord(1)).Return(&testWork{})

	err = x.RunReader.ProcessTransactionLog(context.Background())

	var syncErr *runsync.SyncError
	require.ErrorAs(t, err, &syncErr)
	assert.ErrorIs(t, syncErr.Err, os.ErrPermission)
	assert.Equal(t,
		fmt.Sprintf(
			"Permission error opening file for reading: %s",
			x.TransactionLog),
		syncErr.UserText,
	)
}

func Test_CorruptFileError(t *testing.T) {
	x := setup(t)
	wandbFileWithRecords(t, x.TransactionLog)
	x.MockRecordParser.EXPECT().Parse(isExitRecord(1)).Return(&testWork{})

	// Add data to the file that doesn't follow the LevelDB format.
	wandbFile, err := os.OpenFile(x.TransactionLog, os.O_APPEND|os.O_WRONLY, 0)
	require.NoError(t, err)
	_, err = wandbFile.WriteString("incorrect")
	require.NoError(t, err)
	require.NoError(t, wandbFile.Close())

	err = x.RunReader.ProcessTransactionLog(context.Background())

	assert.ErrorContains(t, err, "error getting next record")
}
