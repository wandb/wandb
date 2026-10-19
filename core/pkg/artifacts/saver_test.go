package artifacts

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/filetransfertest"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestSaveGraphQLRequest(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("CreateArtifact"),
		`{
			"createArtifact": {
				"artifact": {
					"id": "artifact-id",
					"state": "PENDING"
				}
			}
		}`,
	)
	mockGQL.StubMatchOnce( // first createManifest request
		gqlmock.WithOpName("CreateArtifactManifest"),
		`{"createArtifactManifest": {}}`,
	)
	mockGQL.StubMatchOnce( // second one, before uploading the manifest
		gqlmock.WithOpName("CreateArtifactManifest"),
		`{
			"createArtifactManifest": {
				"artifactManifest": {
					"file": {
						"uploadUrl": "test-url"
					}
				}
			}
		}`,
	)
	ftm := filetransfertest.NewFakeFileTransferManager()
	ftm.ShouldCompleteImmediately = true
	saver := NewArtifactSaveManager(
		observabilitytest.NewTestLogger(t),
		observability.NewPrinter(0),
		mockGQL,
		ftm,
		func() bool { return true },
		func() bool { return false },
	)

	result := <-saver.Save(
		context.Background(),
		&spb.ArtifactRecord{
			Entity: "test-entity",
			Manifest: &spb.ArtifactManifest{
				Version: 1,
			},
		},
		0,
		"",
	)

	assert.NoError(t, result.Err)
	requests := mockGQL.AllRequests()
	assert.Len(t, requests, 3)
	createArtifactRequest := requests[0]
	gqlmock.AssertVariables(t,
		createArtifactRequest,
		gqlmock.GQLVar("input.entityName", gomock.Eq("test-entity")))
}

// TestSave_CleansUpManifestFileInStagingDir verifies that the manifest temp
// file written into the staging dir during Save is removed afterwards, leaving
// the staging dir clean (the SDK relies on this — staged files must not linger).
func TestSave_CleansUpManifestFileInStagingDir(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("CreateArtifact"),
		`{
			"createArtifact": {
				"artifact": {
					"id": "artifact-id",
					"state": "PENDING"
				}
			}
		}`,
	)
	mockGQL.StubMatchOnce( // first createManifest request
		gqlmock.WithOpName("CreateArtifactManifest"),
		`{"createArtifactManifest": {}}`,
	)
	mockGQL.StubMatchOnce( // second one, before uploading the manifest
		gqlmock.WithOpName("CreateArtifactManifest"),
		`{
			"createArtifactManifest": {
				"artifactManifest": {
					"file": {
						"uploadUrl": "test-url"
					}
				}
			}
		}`,
	)
	ftm := filetransfertest.NewFakeFileTransferManager()
	ftm.ShouldCompleteImmediately = true
	saver := NewArtifactSaveManager(
		observabilitytest.NewTestLogger(t),
		observability.NewPrinter(0),
		mockGQL,
		ftm,
		func() bool { return true },
		func() bool { return false },
	)

	stagingDir := t.TempDir()
	result := <-saver.Save(
		context.Background(),
		&spb.ArtifactRecord{
			Entity: "test-entity",
			Manifest: &spb.ArtifactManifest{
				Version: 1,
			},
		},
		0,
		stagingDir,
	)

	assert.NoError(t, result.Err)
	entries, err := os.ReadDir(stagingDir)
	assert.NoError(t, err)
	assert.Empty(t, entries,
		"manifest temp file should be removed, leaving the staging dir clean")
}

func TestSave_PreservesInputsOnFailure(t *testing.T) {
	for _, hasStagingDir := range []bool{false, true} {
		name := "without staging directory"
		if hasStagingDir {
			name = "with staging directory"
		}
		t.Run(name, func(t *testing.T) {
			dir := t.TempDir()
			input := filepath.Join(dir, "file.txt")
			require.NoError(t, os.WriteFile(input, []byte("hello"), 0o600))
			stagingDir := ""
			if hasStagingDir {
				stagingDir = dir
			}

			mockGQL := gqlmock.NewMockClient()
			mockGQL.StubMatchWithError(gqlmock.WithOpName("CreateArtifact"), context.Canceled)
			mockGQL.StubMatchOnce(gqlmock.WithOpName("CreateArtifact"),
				`{"createArtifact":{"artifact":{"id":"artifact-id","state":"COMMITTED"}}}`)
			saver := NewArtifactSaveManager(
				observabilitytest.NewTestLogger(t), observability.NewPrinter(0), mockGQL,
				filetransfertest.NewFakeFileTransferManager(),
				func() bool { return true }, func() bool { return false },
			)
			artifact := &spb.ArtifactRecord{
				Manifest: &spb.ArtifactManifest{Contents: []*spb.ArtifactManifestEntry{{
					Path: "file.txt", Digest: "XUFAKrxLKna5cZ2REBfFkg==", Size: 5, LocalPath: input,
				}}},
			}

			result := <-saver.Save(context.Background(), artifact, 0, stagingDir)
			require.ErrorIs(t, result.Err, context.Canceled)
			require.FileExists(t, input)
			result = <-saver.Save(context.Background(), artifact, 0, stagingDir)
			require.NoError(t, result.Err)
			assert.Equal(t, "artifact-id", result.ArtifactID)
		})
	}
}

func TestSave_DeletesOnlyStagingFiles(t *testing.T) {
	for _, tt := range []struct {
		name         string
		stagingDir   string
		inputDir     string
		shouldDelete bool
	}{
		{"staging file", "staging", "staging", true},
		{"nested staging file", "staging", "staging/nested", true},
		{"no staging directory", "", "source", false},
		{"sibling directory", "staging", "staging-other", false},
	} {
		t.Run(tt.name, func(t *testing.T) {
			dir := t.TempDir()
			input := filepath.Join(dir, tt.inputDir, "file.txt")
			require.NoError(t, os.MkdirAll(filepath.Dir(input), 0o700))
			require.NoError(t, os.WriteFile(input, []byte("hello"), 0o400))
			stagingDir := ""
			if tt.stagingDir != "" {
				stagingDir = filepath.Join(dir, tt.stagingDir)
			}

			mockGQL := gqlmock.NewMockClient()
			mockGQL.StubMatchOnce(gqlmock.WithOpName("CreateArtifact"),
				`{"createArtifact":{"artifact":{"id":"artifact-id","state":"COMMITTED"}}}`)
			saver := NewArtifactSaveManager(
				observabilitytest.NewTestLogger(t), observability.NewPrinter(0), mockGQL,
				filetransfertest.NewFakeFileTransferManager(),
				func() bool { return true }, func() bool { return false },
			)
			result := <-saver.Save(context.Background(), &spb.ArtifactRecord{
				Manifest: &spb.ArtifactManifest{Contents: []*spb.ArtifactManifestEntry{{
					Path: "file.txt", Digest: "XUFAKrxLKna5cZ2REBfFkg==", Size: 5, LocalPath: input,
				}}},
			}, 0, stagingDir)

			require.NoError(t, result.Err)
			if tt.shouldDelete {
				assert.NoFileExists(t, input)
			} else {
				assert.FileExists(t, input)
			}
		})
	}
}

func TestSave_MissingMD5File(t *testing.T) {
	for _, state := range []string{"COMMITTED", "PENDING"} {
		t.Run(state, func(t *testing.T) {
			mockGQL := gqlmock.NewMockClient()
			mockGQL.StubMatchOnce(
				gqlmock.WithOpName("CreateArtifact"),
				fmt.Sprintf(
					`{"createArtifact":{"artifact":{"id":"artifact-id","state":%q}}}`,
					state,
				),
			)
			if state == "PENDING" {
				mockGQL.StubMatchOnce(gqlmock.WithOpName("CreateArtifactManifest"),
					`{"createArtifactManifest":{}}`)
			}
			saver := NewArtifactSaveManager(
				observabilitytest.NewTestLogger(t), observability.NewPrinter(0), mockGQL,
				filetransfertest.NewFakeFileTransferManager(),
				func() bool { return true }, func() bool { return false },
			)
			result := <-saver.Save(context.Background(), &spb.ArtifactRecord{
				Manifest: &spb.ArtifactManifest{Contents: []*spb.ArtifactManifestEntry{{
					Path: "file.txt", Digest: "XUFAKrxLKna5cZ2REBfFkg==", Size: 5,
					LocalPath: filepath.Join(t.TempDir(), "removed-staging-file"),
				}}},
			}, 0, "")

			if state == "PENDING" {
				require.ErrorContains(
					t,
					result.Err,
					"ArtifactSaver.uploadFiles: failed to get file size",
				)
			} else {
				require.NoError(t, result.Err)
				assert.Equal(t, "artifact-id", result.ArtifactID)
			}
		})
	}
}

func newSaveManagerWithPrinter(
	t *testing.T,
	mockGQL *gqlmock.MockClient,
	transfers filetransfer.FileTransferManager,
) (*ArtifactSaveManager, *observability.Printer) {
	t.Helper()
	printer := observability.NewPrinter(100)
	manager := NewArtifactSaveManager(
		observabilitytest.NewTestLogger(t), printer, mockGQL, transfers,
		func() bool { return true }, func() bool { return false },
	)
	manager.fileCache = NewFileCache(t.TempDir())
	return manager, printer
}

func emptyArtifact(name string) *spb.ArtifactRecord {
	return &spb.ArtifactRecord{
		Name:     name,
		Type:     "dataset",
		Manifest: &spb.ArtifactManifest{Version: 1},
	}
}

// failingTransferManager fails every upload task, cancelling a context
// first if cancel is set.
type failingTransferManager struct {
	*filetransfertest.FakeFileTransferManager
	cancel context.CancelFunc
	err    error
}

func (m *failingTransferManager) AddTask(task filetransfer.Task) {
	if m.cancel != nil {
		m.cancel()
	}
	task.SetError(m.err)
	task.Complete(nil)
}

func TestSave_FailurePrintsWarning(t *testing.T) {
	saveErr := errors.New("forced artifact failure")
	mockGQL := gqlmock.NewMockClient()
	manager, printer := newSaveManagerWithPrinter(
		t, mockGQL, filetransfertest.NewFakeFileTransferManager(),
	)

	names := []string{"first-artifact", "second-artifact"}
	for _, name := range names {
		mockGQL.StubMatchWithError(
			gqlmock.WithOpName("CreateArtifact"),
			saveErr,
		)
		result := <-manager.Save(context.Background(), emptyArtifact(name), 0, "")
		require.ErrorIs(t, result.Err, saveErr)
	}

	messages := printer.Read()
	require.Len(t, messages, 2)
	for i, message := range messages {
		assert.Equal(t, observability.Warning, message.Severity)
		want := fmt.Sprintf(
			"Failed to save artifact %q (type %q). "+
				"See the run's debug-internal.log for details.",
			names[i], "dataset",
		)
		assert.Equal(t, want, message.Content)
	}
}

func TestSave_SuccessPrintsNoWarning(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("CreateArtifact"),
		`{"createArtifact":{"artifact":{"id":"artifact-id","state":"COMMITTED"}}}`,
	)
	manager, printer := newSaveManagerWithPrinter(
		t, mockGQL, filetransfertest.NewFakeFileTransferManager(),
	)

	result := <-manager.Save(context.Background(), emptyArtifact("ok-artifact"), 0, "")

	require.NoError(t, result.Err)
	for _, msg := range printer.Read() {
		assert.NotContains(t, msg.Content, "Failed to save artifact")
	}
}

func TestSave_CancelledContextPrintsNoWarning(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchWithError(gqlmock.WithOpName("CreateArtifact"), context.Canceled)
	manager, printer := newSaveManagerWithPrinter(
		t, mockGQL, filetransfertest.NewFakeFileTransferManager(),
	)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	result := <-manager.Save(ctx, emptyArtifact("aborted-artifact"), 0, "")

	require.Error(t, result.Err)
	assert.Empty(t, printer.Read())
}

// When uploads fail, the saver's error no longer wraps context.Canceled, so
// the warning check must look at the context rather than the error.
func TestSave_CancelledMidSavePrintsNoWarning(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("CreateArtifact"),
		`{"createArtifact":{"artifact":{"id":"artifact-id","state":"PENDING"}}}`,
	)
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("CreateArtifactManifest"),
		`{"createArtifactManifest":{"artifactManifest":{"id":"manifest-id","file":{"uploadUrl":"https://example.invalid/manifest"}}}}`,
	)
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("CreateArtifactFiles"),
		`{"createArtifactFiles":{"files":{"edges":[{"node":{"artifact":{"id":"artifact-id"},"uploadUrl":"https://example.invalid/data"}}]}}}`,
	)
	transfers := &failingTransferManager{
		FakeFileTransferManager: filetransfertest.NewFakeFileTransferManager(),
		cancel:                  cancel,
		err:                     errors.New("forced failure"),
	}
	manager, printer := newSaveManagerWithPrinter(t, mockGQL, transfers)
	input := filepath.Join(t.TempDir(), "file.txt")
	require.NoError(t, os.WriteFile(input, []byte("hello"), 0o600))
	artifact := emptyArtifact("aborted-artifact")
	artifact.Manifest.Contents = []*spb.ArtifactManifestEntry{{
		Path:      "file.txt",
		Digest:    "XUFAKrxLKna5cZ2REBfFkg==",
		Size:      5,
		LocalPath: input,
		SkipCache: true,
	}}

	result := <-manager.Save(ctx, artifact, 0, "")

	require.ErrorContains(t, result.Err, "most remaining uploads")
	assert.Empty(t, printer.Read())
}
