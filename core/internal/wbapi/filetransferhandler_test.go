package wbapi_test

import (
	"context"
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

// fakeFileTransferManager completes each task using the given callback.
type fakeFileTransferManager struct {
	tasks []filetransfer.Task
	run   func(filetransfer.Task)
}

func (m *fakeFileTransferManager) AddTask(task filetransfer.Task) {
	m.tasks = append(m.tasks, task)
	if m.run != nil {
		m.run(task)
	}
	task.Complete(nil)
}

func (m *fakeFileTransferManager) Close() {}

func TestDownloadFileWritesFile(t *testing.T) {
	content := []byte("downloaded")
	path := filepath.Join(t.TempDir(), "model.bin")
	manager := &fakeFileTransferManager{
		run: func(task filetransfer.Task) {
			downloadTask := task.(*filetransfer.DefaultDownloadTask)
			require.NoError(t, os.WriteFile(downloadTask.Path, content, 0o600))
		},
	}
	handler := wbapi.NewFileTransferHandler(manager)

	response := handler.HandleDownloadFile(
		context.Background(),
		&spb.DownloadFileRequest{
			Path: path,
			Url:  "https://files.example/model.bin",
			Size: 42,
		},
	)

	require.NotNil(t, response.GetDownloadFileResponse())
	data, err := os.ReadFile(path)
	require.NoError(t, err)
	assert.Equal(t, content, data)
	require.Len(t, manager.tasks, 1)
	task := manager.tasks[0].(*filetransfer.DefaultDownloadTask)
	assert.Equal(t, path, task.Path)
	assert.Equal(t, "https://files.example/model.bin", task.Url)
	assert.Equal(t, int64(42), task.Size)
}

func TestDownloadFileReturnsTaskHTTPError(t *testing.T) {
	manager := &fakeFileTransferManager{
		run: func(task filetransfer.Task) {
			downloadTask := task.(*filetransfer.DefaultDownloadTask)
			downloadTask.Response = &http.Response{StatusCode: http.StatusNotFound}
			downloadTask.SetError(errors.New("failed to download: status: 404 Not Found"))
		},
	}
	handler := wbapi.NewFileTransferHandler(manager)

	response := handler.HandleDownloadFile(
		context.Background(),
		&spb.DownloadFileRequest{
			Path: filepath.Join(t.TempDir(), "model.bin"),
			Url:  "https://files.example/model.bin",
		},
	)

	apiError := response.GetApiErrorResponse()
	require.NotNil(t, apiError)
	assert.Equal(t, int32(http.StatusNotFound), apiError.GetHttpStatus())
	assert.Contains(t, apiError.GetMessage(), "404 Not Found")
}

func TestUploadFileSendsTask(t *testing.T) {
	manager := &fakeFileTransferManager{}
	handler := wbapi.NewFileTransferHandler(manager)

	response := handler.HandleUploadFile(
		context.Background(),
		&spb.UploadFileRequest{
			Path:    "/tmp/model.bin",
			Url:     "https://files.example/model.bin",
			Headers: map[string]string{"X-Test": "value"},
		},
	)

	require.NotNil(t, response.GetUploadFileResponse())
	require.Len(t, manager.tasks, 1)
	task := manager.tasks[0].(*filetransfer.DefaultUploadTask)
	assert.Equal(t, "/tmp/model.bin", task.Path)
	assert.Equal(t, "https://files.example/model.bin", task.Url)
	assert.Equal(t, http.Header{"X-Test": {"value"}}, task.Headers)
}

func TestUploadFileReturnsTaskHTTPError(t *testing.T) {
	manager := &fakeFileTransferManager{
		run: func(task filetransfer.Task) {
			uploadTask := task.(*filetransfer.DefaultUploadTask)
			uploadTask.Response = &http.Response{StatusCode: http.StatusForbidden}
			uploadTask.SetError(errors.New("failed to upload: status: 403 Forbidden"))
		},
	}
	handler := wbapi.NewFileTransferHandler(manager)

	response := handler.HandleUploadFile(
		context.Background(),
		&spb.UploadFileRequest{
			Path: "/tmp/model.bin",
			Url:  "https://files.example/model.bin",
		},
	)

	apiError := response.GetApiErrorResponse()
	require.NotNil(t, apiError)
	assert.Equal(t, int32(http.StatusForbidden), apiError.GetHttpStatus())
	assert.Contains(t, apiError.GetMessage(), "403 Forbidden")
}
