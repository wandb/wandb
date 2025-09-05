package runsync_test

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runsync"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/stream"
	"github.com/wandb/wandb/core/internal/streamtest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"go.uber.org/mock/gomock"
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
		Logger: observability.NewNoOpLogger(),
	}

	return testFixtures{
		RunReader: factory.New(
			transactionLog,
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

	store := stream.NewStore(path)

	err := store.Open(os.O_WRONLY)
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

	err := x.RunReader.ProcessTransactionLog()
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

	err := x.RunReader.ProcessTransactionLog()
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

	err := x.RunReader.ProcessTransactionLog()
	require.NoError(t, err)

	assert.Equal(t,
		[]runwork.Work{runWork, runStartWork, exitWork},
		x.FakeRunWork.AllWork())
}

func Test_FileNotFoundError(t *testing.T) {
	x := setup(t)
	x.MockRecordParser.EXPECT().Parse(isExitRecord(1)).Return(&testWork{})

	err := x.RunReader.ProcessTransactionLog()

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

	err = x.RunReader.ProcessTransactionLog()

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
	_, err = wandbFile.Write([]byte("incorrect"))
	require.NoError(t, err)
	require.NoError(t, wandbFile.Close())

	err = x.RunReader.ProcessTransactionLog()

	assert.ErrorContains(t, err, "failed to get next record")
}
