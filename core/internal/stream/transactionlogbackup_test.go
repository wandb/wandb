package stream

import (
	"bytes"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/runconsolelogs"
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/internal/runupserter"
	"github.com/wandb/wandb/core/internal/runupsertertest"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/transactionlog"
	"github.com/wandb/wandb/core/internal/transactionlogtest"
	"github.com/wandb/wandb/core/internal/watchertest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func newSnapshotWriter(t *testing.T) (*Writer, *os.File) {
	t.Helper()
	logWriter, path := transactionlogtest.NewWriter(t, &transactionlogtest.WriterOptions{})
	file, err := os.Open(path)
	require.NoError(t, err)
	t.Cleanup(func() { _ = file.Close() })
	writer := (&WriterFactory{
		Logger:   observabilitytest.NewTestLogger(t),
		Settings: settings.From(&spb.Settings{}),
	}).New(logWriter)
	return writer, file
}

func startSnapshotWriter(t *testing.T, writer *Writer) (chan<- runwork.Work, func()) {
	t.Helper()
	input := make(chan runwork.Work)
	go writer.Do(input)
	var once sync.Once
	stop := func() {
		once.Do(func() {
			close(input)
			for range writer.Chan() {
			}
		})
	}
	t.Cleanup(stop)
	return input, stop
}

func writeBackupRecord(t *testing.T, input chan<- runwork.Work, writer *Writer, record *spb.Record) {
	t.Helper()
	input <- runwork.NoRequest(runwork.WorkFromRecord(record))
	require.True(t, (<-writer.Chan()).IsSaved)
}

func readBackupRecords(t *testing.T, data []byte, expected ...*spb.Record) {
	t.Helper()
	reader, err := transactionlog.NewReader(io.NopCloser(bytes.NewReader(data)), observabilitytest.NewTestLogger(t))
	require.NoError(t, err)
	defer reader.Close()
	for _, want := range expected {
		got, err := reader.Read()
		require.NoError(t, err)
		assert.True(t, proto.Equal(want, got), "got %v, want %v", got, want)
	}
	_, err = reader.Read()
	assert.ErrorIs(t, err, io.EOF)
}

type backupDrainRecorder struct {
	uploaded chan struct{}
}

func (r *backupDrainRecorder) Process(*spb.FilesRecord) {}
func (r *backupDrainRecorder) UploadNow(paths.RelativePath, filetransfer.RunFileKind) {
	r.uploaded <- struct{}{}
}
func (r *backupDrainRecorder) UploadAtEnd(paths.RelativePath, filetransfer.RunFileKind) {}
func (r *backupDrainRecorder) UploadRemaining()                                         {}
func (r *backupDrainRecorder) Finish()                                                  {}

type backupFinishFixture struct {
	sender  *Sender
	source  *os.File
	exit    *spb.Record
	drained <-chan struct{}
}

func newBackupFinishFixture(t *testing.T) *backupFinishFixture {
	t.Helper()
	writer, source := newSnapshotWriter(t)
	input, _ := startSnapshotWriter(t, writer)
	exit := &spb.Record{RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{}}}
	writeBackupRecord(t, input, writer, exit)

	cfg := settings.From(&spb.Settings{
		SyncDir: wrapperspb.String(t.TempDir()), SyncFile: wrapperspb.String(source.Name()),
		XPrimary: wrapperspb.Bool(true), XTransactionLogBackup: wrapperspb.String("s3://backup-bucket/prefix/"),
	})
	require.NoError(t, os.MkdirAll(cfg.GetFilesDir(), 0700))
	handle := runhandle.New()
	upserter := runupsertertest.NewTestUpserter(t, "entity", "project", "run-id", runupserter.RunUpserterParams{Settings: cfg})
	require.NoError(t, handle.Init(upserter))
	work := runworktest.New()
	t.Cleanup(work.Abort)
	drained := make(chan struct{}, 2)
	logger := observabilitytest.NewTestLogger(t)
	sender := &Sender{
		runWork: work, logger: logger, settings: cfg, runHandle: handle,
		printer: observability.NewPrinter(16), receivedExitCh: make(chan struct{}),
		transactionLogBackup: &transactionLogBackup{writer: writer, executionID: "execution-id"},
		fileTransferStats:    filetransfer.NewFileTransferStats(), fileWatcher: watchertest.NewFakeWatcher(),
		runfilesUploader: &backupDrainRecorder{uploaded: drained}, runSummary: runsummary.New(),
		consoleLogsSender: runconsolelogs.New(runconsolelogs.Params{Logger: logger}),
	}
	return &backupFinishFixture{sender: sender, source: source, exit: exit, drained: drained}
}

func (f *backupFinishFixture) finish(t *testing.T) <-chan *spb.ServerResponse {
	t.Helper()
	request, responses := runworktest.SimpleRequest(t, "exit")
	f.sender.SendRecord(f.exit, request)
	return responses
}

func (f *backupFinishFixture) checkFinished(t *testing.T, responses <-chan *spb.ServerResponse, warning bool) {
	t.Helper()
	select {
	case response := <-responses:
		require.NotNil(t, response.GetResultCommunicate().GetExitResult())
		assert.False(t, response.GetResultCommunicate().GetExitResult().TimedOut)
	case <-time.After(5 * time.Second):
		t.Fatal("finish did not respond")
	}
	messages := f.sender.printer.Read()
	if warning {
		require.Len(t, messages, 1)
		assert.Equal(t, observability.Warning, messages[0].Severity)
	} else {
		assert.Empty(t, messages)
	}
	require.FileExists(t, f.source.Name())
}

func blockingBackupServer(t *testing.T) (<-chan struct{}, func()) {
	t.Helper()
	entered, release := make(chan struct{}, 1), make(chan struct{})
	var once sync.Once
	unblock := func() { once.Do(func() { close(release) }) }
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if _, err := io.Copy(io.Discard, r.Body); err != nil {
			return
		}
		select {
		case entered <- struct{}{}:
		case <-r.Context().Done():
			return
		}
		select {
		case <-release:
			w.Header().Set("ETag", `"backup"`)
			w.WriteHeader(http.StatusOK)
		case <-r.Context().Done():
		}
	}))
	t.Cleanup(server.Close)
	t.Cleanup(unblock)
	for key, value := range map[string]string{
		"AWS_ACCESS_KEY_ID": "local-smoke", "AWS_SECRET_ACCESS_KEY": "local-smoke",
		"AWS_REGION": "us-east-1", "AWS_ENDPOINT_URL_S3": server.URL,
		"AWS_EC2_METADATA_DISABLED": "true",
	} {
		t.Setenv(key, value)
	}
	return entered, unblock
}

func TestTransactionLogBackupFinishWaitsForCommit(t *testing.T) {
	entered, unblock := blockingBackupServer(t)
	f := newBackupFinishFixture(t)

	responses := f.finish(t)

	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		t.Fatal("bucket upload did not start")
	}
	for range 2 {
		select {
		case <-f.drained:
		case <-time.After(5 * time.Second):
			t.Fatal("normal draining stalled")
		}
	}

	select {
	case <-responses:
		t.Fatal("finish responded before bucket commitment")
	default:
	}

	duplicate, duplicateResponses := runworktest.SimpleRequest(t, "duplicate")
	f.sender.SendRecord(f.exit, duplicate)

	require.NotNil(t, (<-duplicateResponses).GetErrorResponse())

	unblock()

	f.checkFinished(t, responses, false)
}

func TestTransactionLogBackupFinishTimeout(t *testing.T) {
	entered, _ := blockingBackupServer(t)
	f := newBackupFinishFixture(t)
	f.sender.settings.Proto.XTransactionLogBackupTimeout = wrapperspb.Double(0.5)

	responses := f.finish(t)

	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		t.Fatal("bucket upload did not start")
	}

	f.checkFinished(t, responses, true)
}

func TestTransactionLogBackupFinishMissingLog(t *testing.T) {
	f := newBackupFinishFixture(t)
	f.sender.settings.Proto.SyncFile = wrapperspb.String(f.source.Name() + ".missing")

	f.checkFinished(t, f.finish(t), true)
}
