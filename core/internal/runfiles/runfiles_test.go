package runfiles_test

import (
	"os"
	"path/filepath"
	"syscall"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
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
		`{
			"createRunFiles": {
				"runID": "test-run",
				"files": [
					{
						"name": "test-file",
						"uploadUrl": "https://example.com/test-file"
					}
				]
			}
		}`,
	)
}

func writeEmptyFile(t *testing.T, path string) {
	require.NoError(t,
		os.MkdirAll(
			filepath.Dir(path),
			syscall.S_IRUSR|syscall.S_IWUSR|syscall.S_IXUSR,
		),
	)

	require.NoError(t,
		os.WriteFile(path, []byte(""), os.FileMode(0)),
	)
}

func TestUploader(t *testing.T) {
	var fakeFileTransfer *filetransfertest.FakeFileTransferManager
	var mockGQLClient *gqlmock.MockClient
	var uploader Uploader

	// The files_dir to set on Settings.
	var filesDir string

	// The _offline mode to set on Settings.
	var isOffline bool

	// The _sync mode to set on Settings.
	var isSync bool

	// Resets test objects and runs a given test.
	runTest := func(
		name string,
		configure func(),
		test func(t *testing.T),
	) {
		// Set a default and allow tests to override it.
		filesDir = t.TempDir()
		isOffline = false
		isSync = false
		configure()

		fakeFileTransfer = filetransfertest.NewFakeFileTransferManager()
		fakeFileTransfer.ShouldCompleteImmediately = true

		mockGQLClient = gqlmock.NewMockClient()

		uploader = NewUploader(runfilestest.WithTestDefaults(UploaderParams{
			GraphQL:      mockGQLClient,
			FileTransfer: fakeFileTransfer,
			Settings: settings.From(&service.Settings{
				FilesDir: &wrapperspb.StringValue{Value: filesDir},
				XOffline: &wrapperspb.BoolValue{Value: isOffline},
				XSync:    &wrapperspb.BoolValue{Value: isSync},
			}),
		}))

		t.Run(name, test)
	}

	runTest("Process with 'now' policy uploads immediately",
		func() {},
		func(t *testing.T) {
			stubCreateRunFilesOneFile(mockGQLClient)
			writeEmptyFile(t, filepath.Join(filesDir, "test.txt"))

			uploader.Process(&service.FilesRecord{
				Files: []*service.FilesItem{
					{Path: "test.txt", Policy: service.FilesItem_NOW},
				},
			})
			uploader.Finish()

			assert.Len(t, fakeFileTransfer.Tasks(), 1)
		})

	runTest("Process with 'now' policy during sync is no-op",
		func() { isSync = true },
		func(t *testing.T) {
			stubCreateRunFilesOneFile(mockGQLClient)

			uploader.Process(&service.FilesRecord{
				Files: []*service.FilesItem{
					{Path: "test.txt", Policy: service.FilesItem_NOW},
				},
			})
			uploader.Finish()

			assert.Len(t, fakeFileTransfer.Tasks(), 0)
		})

	runTest("UploadNow uploads given file",
		func() {},
		func(t *testing.T) {
			stubCreateRunFilesOneFile(mockGQLClient)
			writeEmptyFile(t, filepath.Join(filesDir, "subdir", "test.txt"))

			uploader.UploadNow(filepath.Join("subdir", "test.txt"))
			uploader.Finish()

			assert.Len(t, fakeFileTransfer.Tasks(), 1)
		})

	runTest("UploadNow ignores non-existent file",
		func() {},
		func(t *testing.T) {
			stubCreateRunFilesOneFile(mockGQLClient)

			uploader.UploadNow(filepath.Join("subdir", "test.txt"))
			uploader.Finish()

			assert.Len(t, fakeFileTransfer.Tasks(), 0)
		})

	runTest("UploadNow does nothing if offline",
		func() { isOffline = true },
		func(t *testing.T) {
			stubCreateRunFilesOneFile(mockGQLClient)

			uploader.UploadNow(filepath.Join("subdir", "test.txt"))
			uploader.Finish()

			assert.Len(t, fakeFileTransfer.Tasks(), 0)
		})

	runTest("upload is no-op if GraphQL returns wrong number of files",
		func() {},
		func(t *testing.T) {
			stubCreateRunFilesOneFile(mockGQLClient)
			writeEmptyFile(t, filepath.Join(filesDir, "file1.txt"))
			writeEmptyFile(t, filepath.Join(filesDir, "file2.txt"))

			// This tries to upload 2 files, but GraphQL returns 1 file.
			uploader.UploadRemaining()
			uploader.Finish()

			assert.Len(t, fakeFileTransfer.Tasks(), 0)
		})

	runTest("UploadRemaining uploads all files using GraphQL response",
		func() { filesDir = filepath.Join(t.TempDir(), "files") },
		func(t *testing.T) {
			mockGQLClient.StubMatchOnce(
				gqlmock.WithOpName("CreateRunFiles"),
				`{
					"createRunFiles": {
						"runID": "test-run",
						"uploadHeaders": ["Header1:Value1", "Header2:Value2"],
						"files": [
							{
								"name": "test-file1",
								"uploadUrl": "URL1"
							},
							{
								"name": "subdir/test-file2",
								"uploadUrl": "URL2"
							}
						]
					}
				}`,
			)
			writeEmptyFile(t, filepath.Join(filesDir, "test-file1"))
			writeEmptyFile(t, filepath.Join(filesDir, "subdir", "test-file2"))

			uploader.UploadRemaining()
			uploader.Finish()

			uploadTasks := fakeFileTransfer.Tasks()
			require.Len(t, uploadTasks, 2)

			assert.Equal(t,
				filepath.Join(filesDir, "test-file1"),
				uploadTasks[0].Path)
			assert.Equal(t, "test-file1", uploadTasks[0].Name)
			assert.Equal(t, "URL1", uploadTasks[0].Url)
			assert.Equal(t,
				[]string{"Header1:Value1", "Header2:Value2"},
				uploadTasks[0].Headers)

			assert.Equal(t,
				filepath.Join(filesDir, "subdir", "test-file2"),
				uploadTasks[1].Path)
			assert.Equal(t, "subdir/test-file2", uploadTasks[1].Name)
			assert.Equal(t, "URL2", uploadTasks[1].Url)
			assert.Equal(t,
				[]string{"Header1:Value1", "Header2:Value2"},
				uploadTasks[1].Headers)
		})
}
