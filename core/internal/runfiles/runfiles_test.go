package runfiles_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/filetransfertest"
	"github.com/wandb/wandb/core/internal/gqlmock"
	. "github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/runfilestest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

func stubCreateRunFilesOneFile(mockGQLClient *gqlmock.MockClient) {
	mockGQLClient.StubMatchOnce(
		gqlmock.WithOpName("CreateRunFiles"),
		`"createRunFiles": {
			"runID": "test-run",
			"files": [
				{
					"name": "test-file",
					"uploadUrl": "https://example.com/test-file",
				}
			]
		}`,
	)
}

func TestProcessRecord(t *testing.T) {
	var fakeFileTransfer *filetransfertest.FakeFileTransferManager
	var mockGQLClient *gqlmock.MockClient
	var handler FilesRecordHandler

	// The files_dir to set on Settings.
	var filesDir string

	// Resets test objects and runs a given test.
	runTest := func(
		name string,
		configure func(),
		test func(t *testing.T),
	) {
		filesDir = "default/files/dir"
		configure()

		fakeFileTransfer = filetransfertest.NewFakeFileTransferManager()
		mockGQLClient = gqlmock.NewMockClient()
		handler = New(runfilestest.WithTestDefaults(FilesRecordHandlerParams{
			GraphQL:      mockGQLClient,
			FileTransfer: fakeFileTransfer,
			Settings: settings.From(&service.Settings{
				FilesDir: &wrapperspb.StringValue{Value: filesDir},
			}),
		}))

		t.Run(name, test)
	}

	runTest("'now' uploads immediately", func() {}, func(t *testing.T) {
		t.Skip("Not implemented")
		stubCreateRunFilesOneFile(mockGQLClient)

		handler.ProcessRecord(&service.FilesRecord{
			Files: []*service.FilesItem{
				{Path: "file.txt", Policy: service.FilesItem_NOW},
			},
		})
		handler.Finish() // No flush!

		assert.Len(t, fakeFileTransfer.Tasks(), 1)
	})

	runTest("'end' does not upload immediately", func() {}, func(t *testing.T) {
		t.Skip("Not implemented")
		stubCreateRunFilesOneFile(mockGQLClient)

		handler.ProcessRecord(&service.FilesRecord{
			Files: []*service.FilesItem{
				{Path: "file.txt", Policy: service.FilesItem_END},
			},
		})
		handler.Finish() // No flush!

		assert.Len(t, fakeFileTransfer.Tasks(), 0)
	})

	runTest("'end' uploads after flush", func() {}, func(t *testing.T) {
		t.Skip("Not implemented")
		stubCreateRunFilesOneFile(mockGQLClient)

		handler.ProcessRecord(&service.FilesRecord{
			Files: []*service.FilesItem{
				{Path: "file.txt", Policy: service.FilesItem_END},
			},
		})
		handler.Flush()
		handler.Finish()

		assert.Len(t, fakeFileTransfer.Tasks(), 1)
	})

	runTest("'live' uploads immediately and on flush",
		func() { filesDir = t.TempDir() },
		func(t *testing.T) {
			t.Skip("Not implemented")
			stubCreateRunFilesOneFile(mockGQLClient)

			// First upload (immediate):
			handler.ProcessRecord(&service.FilesRecord{
				Files: []*service.FilesItem{
					{Path: "file.txt", Policy: service.FilesItem_LIVE},
				},
			})

			// Second upload (on flush):
			handler.Flush()

			// Note: we don't test uploads due to changes as they're not very
			// testable.
			handler.Finish()
			assert.Len(t, fakeFileTransfer.Tasks(), 2)
		})

	runTest("uploads using GraphQL response",
		func() { filesDir = "the/files/directory" },
		func(t *testing.T) {
			t.Skip("Not implemented")

			mockGQLClient.StubMatchOnce(
				gqlmock.WithOpName("CreateRunFiles"),
				`"createRunFiles": {
					"runID": "test-run",
					"uploadHeaders": ["Header1:Value1", "Header2:Value2"],
					"files": [
						{
							"name": "test-file",
							"uploadUrl": "https://example.com/test-file",
						}
					]
				}`,
			)

			handler.ProcessRecord(&service.FilesRecord{
				Files: []*service.FilesItem{
					{Path: "file.txt", Policy: service.FilesItem_NOW},
				},
			})
			handler.Finish()

			uploadTasks := fakeFileTransfer.Tasks()
			assert.Len(t, uploadTasks, 1)
			assert.Equal(t,
				&filetransfer.Task{
					Type:    filetransfer.UploadTask,
					Path:    "the/files/directory/file.txt",
					Name:    "test-file",
					Url:     "https://example.com/test-file",
					Headers: []string{"Header1:Value1", "Header2:Value2"},
				},
				uploadTasks[0].Path)
		})
}
