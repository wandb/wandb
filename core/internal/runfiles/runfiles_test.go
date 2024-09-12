package runfiles_test

import (
	"fmt"
	"os"
	"path/filepath"
	"syscall"
	"testing"

	"github.com/golang/mock/gomock"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filestreamtest"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/filetransfertest"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/paths"
	. "github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/runfilestest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/waitingtest"
	"github.com/wandb/wandb/core/internal/watchertest"
	"google.golang.org/protobuf/types/known/wrapperspb"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func stubCreateRunFilesOneFile(
	mockGQLClient *gqlmock.MockClient,
	path string,
) {
	mockGQLClient.StubMatchOnce(
		gqlmock.WithOpName("CreateRunFiles"),
		fmt.Sprintf(`{
			"createRunFiles": {
				"runID": "test-run",
				"files": [
					{
						"name": "%v",
						"uploadUrl": "https://example.com/test-file"
					}
				]
			}
		}`, path),
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

func rel(t *testing.T, path string) paths.RelativePath {
	relPath, err := paths.Relative(path)
	require.NoError(t, err)
	return *relPath
}

func TestUploader(t *testing.T) {
	var fakeFileStream *filestreamtest.FakeFileStream
	var fakeFileTransfer *filetransfertest.FakeFileTransferManager
	var mockGQLClient *gqlmock.MockClient
	var fakeFileWatcher *watchertest.FakeWatcher
	var uploader Uploader

	// Optional batch delay to use in the uploader.
	var batchDelay *waitingtest.FakeDelay

	// The files_dir to set on Settings.
	var filesDir string

	// The ignore_globs to set on Settings.
	var ignoreGlobs []string

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
		batchDelay = nil
		filesDir = t.TempDir()
		ignoreGlobs = []string{}
		isOffline = false
		isSync = false
		configure()

		fakeFileStream = filestreamtest.NewFakeFileStream()

		fakeFileTransfer = filetransfertest.NewFakeFileTransferManager()
		fakeFileTransfer.ShouldCompleteImmediately = true

		mockGQLClient = gqlmock.NewMockClient()

		fakeFileWatcher = watchertest.NewFakeWatcher()

		uploader = NewUploader(runfilestest.WithTestDefaults(UploaderParams{
			GraphQL:      mockGQLClient,
			FileStream:   fakeFileStream,
			FileTransfer: fakeFileTransfer,
			FileWatcher:  fakeFileWatcher,
			BatchDelay:   batchDelay,
			Settings: settings.From(&spb.Settings{
				FilesDir:    &wrapperspb.StringValue{Value: filesDir},
				IgnoreGlobs: &spb.ListStringValue{Value: ignoreGlobs},
				XOffline:    &wrapperspb.BoolValue{Value: isOffline},
				XSync:       &wrapperspb.BoolValue{Value: isSync},
			}),
		}))

		t.Run(name, test)
	}

	policiesUploadImmediately := []spb.FilesItem_PolicyType{
		spb.FilesItem_NOW,
		spb.FilesItem_LIVE,
	}
	for _, policy := range policiesUploadImmediately {
		runTest(fmt.Sprintf("Process with '%v' policy uploads immediately", policy),
			func() {},
			func(t *testing.T) {
				stubCreateRunFilesOneFile(mockGQLClient, "test.txt")
				writeEmptyFile(t, filepath.Join(filesDir, "test.txt"))

				uploader.Process(&spb.FilesRecord{
					Files: []*spb.FilesItem{
						{Path: "test.txt", Policy: policy},
					},
				})
				uploader.Finish()

				assert.Len(t, fakeFileTransfer.Tasks(), 1)
			})
	}

	runTest("Process with 'live' policy watches file",
		func() {},
		func(t *testing.T) {
			writeEmptyFile(t, filepath.Join(filesDir, "test.txt"))

			uploader.Process(&spb.FilesRecord{
				Files: []*spb.FilesItem{
					{Path: "test.txt", Policy: spb.FilesItem_LIVE},
				},
			})
			uploader.Finish()

			assert.True(t,
				fakeFileWatcher.IsWatching(filepath.Join(filesDir, "test.txt")))
		})

	runTest("Process with 'now' policy during sync is no-op",
		func() { isSync = true },
		func(t *testing.T) {
			stubCreateRunFilesOneFile(mockGQLClient, "test.txt")
			writeEmptyFile(t, filepath.Join(filesDir, "test.txt"))

			uploader.Process(&spb.FilesRecord{
				Files: []*spb.FilesItem{
					{Path: "test.txt", Policy: spb.FilesItem_NOW},
				},
			})
			uploader.Finish()

			assert.Len(t, fakeFileTransfer.Tasks(), 0)
		})

	runTest("Process sets file category",
		func() {},
		func(t *testing.T) {
			stubCreateRunFilesOneFile(mockGQLClient, "test.txt")
			writeEmptyFile(t, filepath.Join(filesDir, "test.txt"))

			uploader.Process(&spb.FilesRecord{
				Files: []*spb.FilesItem{
					{
						Path:   "test.txt",
						Policy: spb.FilesItem_NOW,
						Type:   spb.FilesItem_ARTIFACT,
					},
				},
			})
			uploader.Finish()

			assert.Len(t, fakeFileTransfer.Tasks(), 1)
			task, ok := fakeFileTransfer.Tasks()[0].(*filetransfer.DefaultUploadTask)
			assert.Equal(t, ok, true)
			assert.Equal(t,
				filetransfer.RunFileKindArtifact,
				task.FileKind,
			)
		})

	runTest("UploadNow uploads given file",
		func() {},
		func(t *testing.T) {
			stubCreateRunFilesOneFile(mockGQLClient, "subdir/test.txt")
			writeEmptyFile(t, filepath.Join(filesDir, "subdir", "test.txt"))

			uploader.UploadNow(rel(t, filepath.Join("subdir", "test.txt")))
			uploader.Finish()

			assert.Len(t, fakeFileTransfer.Tasks(), 1)
		})

	runTest("UploadNow ignores non-existent file",
		func() {},
		func(t *testing.T) {
			stubCreateRunFilesOneFile(mockGQLClient, "subdir/test.txt")

			uploader.UploadNow(rel(t, filepath.Join("subdir", "test.txt")))
			uploader.Finish()

			assert.Len(t, fakeFileTransfer.Tasks(), 0)
		})

	runTest("UploadNow ignores file matching ignore glob",
		func() { ignoreGlobs = []string{"subdir/*/file.txt"} },
		func(t *testing.T) {
			stubCreateRunFilesOneFile(mockGQLClient, "subdir/xyz/file.txt")
			writeEmptyFile(t, filepath.Join(filesDir, "subdir", "xyz", "file.txt"))

			uploader.UploadNow(rel(t, filepath.Join("subdir", "xyz", "file.txt")))
			uploader.Finish()

			assert.Len(t, fakeFileTransfer.Tasks(), 0)
		})

	runTest("UploadNow does nothing if offline",
		func() { isOffline = true },
		func(t *testing.T) {
			stubCreateRunFilesOneFile(mockGQLClient, "subdir/test.txt")
			writeEmptyFile(t, filepath.Join(filesDir, "subdir", "test.txt"))

			uploader.UploadNow(rel(t, filepath.Join("subdir", "test.txt")))
			uploader.Finish()

			assert.Len(t, fakeFileTransfer.Tasks(), 0)
		})

	runTest("upload signals filestream on success",
		func() {},
		func(t *testing.T) {
			stubCreateRunFilesOneFile(mockGQLClient, "subdir/test.txt")
			writeEmptyFile(t, filepath.Join(filesDir, "subdir", "test.txt"))

			uploader.UploadNow(rel(t, filepath.Join("subdir", "test.txt")))
			uploader.Finish()

			assert.Equal(t,
				[]filestream.Update{
					&filestream.FilesUploadedUpdate{
						RelativePath: filepath.Join("subdir", "test.txt"),
					},
				},
				fakeFileStream.GetUpdates())
		})

	runTest("upload serializes uploads of the same file",
		func() {},
		func(t *testing.T) {
			writeEmptyFile(t, filepath.Join(filesDir, "test.txt"))
			fakeFileTransfer.ShouldCompleteImmediately = false

			// Act 1: trigger two uploads.
			stubCreateRunFilesOneFile(mockGQLClient, "test.txt")
			uploader.UploadNow("test.txt")
			stubCreateRunFilesOneFile(mockGQLClient, "test.txt")
			uploader.UploadNow("test.txt")
			uploader.(UploaderTesting).FlushSchedulingForTest()

			// Assert 1: only one upload task should happen at a time.
			assert.Len(t, fakeFileTransfer.Tasks(), 1)

			// Act 2: complete the first upload task.
			firstUpload := fakeFileTransfer.Tasks()[0]
			firstUpload.Complete(nil)
			uploader.(UploaderTesting).FlushSchedulingForTest()

			// Assert 2: the second upload task should get scheduled.
			assert.Len(t, fakeFileTransfer.Tasks(), 2)
		})

	runTest("upload batches and deduplicates CreateRunFiles calls",
		func() { batchDelay = waitingtest.NewFakeDelay() },
		func(t *testing.T) {
			writeEmptyFile(t, filepath.Join(filesDir, "test1.txt"))
			writeEmptyFile(t, filepath.Join(filesDir, "test2.txt"))
			mockGQLClient.StubMatchOnce(
				gomock.All(
					gqlmock.WithOpName("CreateRunFiles"),
					gqlmock.WithVariables(
						gqlmock.GQLVar("files", gomock.Len(2)),
					),
				),
				`{
					"createRunFiles": {
						"runID": "test-run",
						"uploadHeaders": [],
						"files": [
							{
								"name": "test1.txt",
								"uploadURL": ""
							},
							{
								"name": "test2.txt",
								"uploadURL": ""
							}
						]
					}
				}`,
			)

			uploader.UploadNow("test1.txt")
			uploader.UploadNow("test2.txt")
			uploader.UploadNow("test2.txt")
			batchDelay.SetZero()
			uploader.Finish()

			assert.True(t, mockGQLClient.AllStubsUsed())
		})

	runTest("upload is no-op if GraphQL returns wrong number of files",
		func() {},
		func(t *testing.T) {
			stubCreateRunFilesOneFile(mockGQLClient, "file1.txt")
			writeEmptyFile(t, filepath.Join(filesDir, "file1.txt"))
			writeEmptyFile(t, filepath.Join(filesDir, "file2.txt"))

			// This tries to upload 2 files, but GraphQL returns 1 file.
			uploader.UploadAtEnd("file1.txt")
			uploader.UploadAtEnd("file2.txt")
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

			uploader.UploadAtEnd("test-file1")
			uploader.UploadAtEnd(rel(t, filepath.Join("subdir", "test-file2")))
			uploader.UploadRemaining()
			uploader.Finish()

			uploadTasks := fakeFileTransfer.Tasks()
			require.Len(t, uploadTasks, 2)

			task, ok := uploadTasks[0].(*filetransfer.DefaultUploadTask)
			assert.Equal(t, ok, true)
			assert.Equal(t,
				filepath.Join(filesDir, "test-file1"),
				task.Path)
			assert.Equal(t, "test-file1", task.Name)
			assert.Equal(t, "URL1", task.Url)
			assert.Equal(t,
				[]string{"Header1:Value1", "Header2:Value2"},
				task.Headers)

			task, ok = uploadTasks[1].(*filetransfer.DefaultUploadTask)
			assert.Equal(t, ok, true)
			assert.Equal(t,
				filepath.Join(filesDir, "subdir", "test-file2"),
				task.Path)
			assert.Equal(t, "subdir/test-file2", task.Name)
			assert.Equal(t, "URL2", task.Url)
			assert.Equal(t,
				[]string{"Header1:Value1", "Header2:Value2"},
				task.Headers)
		})
}
