package wbapi_test

import (
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/wbapi"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// fakeFileTransferManager records tasks and, unless deferComplete is set,
// completes each one as soon as it is added.
type fakeFileTransferManager struct {
	tasks         []filetransfer.Task
	run           func(*filetransfer.DefaultDownloadTask)
	deferComplete bool
}

func (m *fakeFileTransferManager) AddTask(task filetransfer.Task) {
	m.tasks = append(m.tasks, task)
	if m.run != nil {
		m.run(task.(*filetransfer.DefaultDownloadTask))
	}
	if !m.deferComplete {
		task.Complete(nil)
	}
}

func (m *fakeFileTransferManager) Close() {}

func (m *fakeFileTransferManager) completeAll() {
	for _, task := range m.tasks {
		task.Complete(nil)
	}
}

// startDownload starts a download and returns its request id.
func startDownload(
	t *testing.T,
	handler *wbapi.FileTransferHandler,
	request *spb.StartFileDownloadRequest,
) int32 {
	t.Helper()
	response := handler.HandleStartFileDownload(request)
	started := response.GetStartFileDownloadResponse()
	require.NotNil(t, started)
	return started.GetRequestId()
}

func TestStartFileDownloadWritesFile(t *testing.T) {
	content := []byte("downloaded")
	path := filepath.Join(t.TempDir(), "model.bin")
	manager := &fakeFileTransferManager{
		run: func(task *filetransfer.DefaultDownloadTask) {
			require.NoError(t, os.WriteFile(task.Path, content, 0o600))
		},
	}
	handler := wbapi.NewFileTransferHandler(manager)

	requestID := startDownload(t, handler, &spb.StartFileDownloadRequest{
		Path: path,
		Url:  "https://files.example/model.bin",
		Size: 42,
	})

	require.Len(t, manager.tasks, 1)
	task := manager.tasks[0].(*filetransfer.DefaultDownloadTask)
	assert.Equal(t, path, task.Path)
	assert.Equal(t, "https://files.example/model.bin", task.Url)
	assert.Equal(t, int64(42), task.Size)

	status := handler.HandleFileDownloadStatus(
		&spb.FileDownloadStatusRequest{RequestId: requestID},
	).GetFileDownloadStatusResponse()
	require.NotNil(t, status)
	assert.True(t, status.GetDone())
	assert.Empty(t, status.GetError())

	data, err := os.ReadFile(path)
	require.NoError(t, err)
	assert.Equal(t, content, data)
}

func TestFileDownloadStatusReportsInProgressThenDone(t *testing.T) {
	manager := &fakeFileTransferManager{deferComplete: true}
	handler := wbapi.NewFileTransferHandler(manager)

	requestID := startDownload(t, handler, &spb.StartFileDownloadRequest{
		Path: filepath.Join(t.TempDir(), "model.bin"),
		Url:  "https://files.example/model.bin",
	})

	inProgress := handler.HandleFileDownloadStatus(
		&spb.FileDownloadStatusRequest{RequestId: requestID},
	).GetFileDownloadStatusResponse()
	require.NotNil(t, inProgress)
	assert.False(t, inProgress.GetDone())

	manager.completeAll()

	done := handler.HandleFileDownloadStatus(
		&spb.FileDownloadStatusRequest{RequestId: requestID},
	).GetFileDownloadStatusResponse()
	require.NotNil(t, done)
	assert.True(t, done.GetDone())
	assert.Empty(t, done.GetError())
}

func TestFileDownloadStatusReturnsTaskError(t *testing.T) {
	manager := &fakeFileTransferManager{
		run: func(task *filetransfer.DefaultDownloadTask) {
			task.Response = &http.Response{StatusCode: http.StatusNotFound}
			task.SetError(errors.New("failed to download: status: 404 Not Found"))
		},
	}
	handler := wbapi.NewFileTransferHandler(manager)

	requestID := startDownload(t, handler, &spb.StartFileDownloadRequest{
		Path: filepath.Join(t.TempDir(), "model.bin"),
		Url:  "https://files.example/model.bin",
	})

	status := handler.HandleFileDownloadStatus(
		&spb.FileDownloadStatusRequest{RequestId: requestID},
	).GetFileDownloadStatusResponse()
	require.NotNil(t, status)
	assert.True(t, status.GetDone())
	assert.Contains(t, status.GetError(), "404 Not Found")
}

func TestFileDownloadStatusForgetsCompletedDownload(t *testing.T) {
	manager := &fakeFileTransferManager{}
	handler := wbapi.NewFileTransferHandler(manager)

	requestID := startDownload(t, handler, &spb.StartFileDownloadRequest{
		Path: filepath.Join(t.TempDir(), "model.bin"),
		Url:  "https://files.example/model.bin",
	})

	first := handler.HandleFileDownloadStatus(
		&spb.FileDownloadStatusRequest{RequestId: requestID},
	).GetFileDownloadStatusResponse()
	require.NotNil(t, first)
	assert.True(t, first.GetDone())

	// A finished download is forgotten, so polling again is an error.
	second := handler.HandleFileDownloadStatus(
		&spb.FileDownloadStatusRequest{RequestId: requestID},
	)
	require.NotNil(t, second.GetApiErrorResponse())
}

func TestFileDownloadStatusUnknownRequestID(t *testing.T) {
	handler := wbapi.NewFileTransferHandler(&fakeFileTransferManager{})

	response := handler.HandleFileDownloadStatus(
		&spb.FileDownloadStatusRequest{RequestId: 123},
	)

	apiError := response.GetApiErrorResponse()
	require.NotNil(t, apiError)
	assert.Contains(t, apiError.GetMessage(), "not found")
}
