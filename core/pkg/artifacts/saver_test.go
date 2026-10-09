package artifacts

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"

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
) (*ArtifactSaveManager, *observability.Printer) {
	t.Helper()
	printer := observability.NewPrinter(100)
	manager := NewArtifactSaveManager(
		observabilitytest.NewTestLogger(t), printer, mockGQL,
		filetransfertest.NewFakeFileTransferManager(),
		func() bool { return true }, func() bool { return false },
	)
	return manager, printer
}

func failedSaveMessages(printer *observability.Printer) []observability.PrinterMessage {
	var failures []observability.PrinterMessage
	for _, msg := range printer.Read() {
		if strings.Contains(msg.Content, "Failed to save artifact") {
			failures = append(failures, msg)
		}
	}
	return failures
}

func TestSave_FailurePrintsWarning(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchWithError(
		gqlmock.WithOpName("CreateArtifact"),
		errors.New("forced artifact failure"),
	)
	saver, printer := newSaveManagerWithPrinter(t, mockGQL)

	result := <-saver.Save(
		context.Background(),
		&spb.ArtifactRecord{
			Name:     "failing-artifact",
			Type:     "dataset",
			Manifest: &spb.ArtifactManifest{Version: 1},
		},
		0,
		"",
	)

	require.Error(t, result.Err)
	messages := printer.Read()
	require.Len(t, messages, 1)
	assert.Equal(t, observability.Warning, messages[0].Severity)
	assert.Contains(t, messages[0].Content, `"failing-artifact"`)
	assert.Contains(t, messages[0].Content, `"dataset"`)
	assert.Contains(t, messages[0].Content, "forced artifact failure")
}

func TestSave_DistinctFailuresPrintSeparateWarnings(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchWithError(
		gqlmock.WithOpName("CreateArtifact"),
		errors.New("forced artifact failure"),
	)
	saver, printer := newSaveManagerWithPrinter(t, mockGQL)

	for _, name := range []string{"first-artifact", "second-artifact"} {
		result := <-saver.Save(
			context.Background(),
			&spb.ArtifactRecord{
				Name:     name,
				Type:     "dataset",
				Manifest: &spb.ArtifactManifest{Version: 1},
			},
			0,
			"",
		)
		require.Error(t, result.Err)
	}

	messages := printer.Read()
	require.Len(t, messages, 2)
	assert.Contains(t, messages[0].Content, `"first-artifact"`)
	assert.Contains(t, messages[1].Content, `"second-artifact"`)
}

func TestSave_SuccessPrintsNoFailureWarning(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(gqlmock.WithOpName("CreateArtifact"),
		`{"createArtifact":{"artifact":{"id":"artifact-id","state":"COMMITTED"}}}`)
	saver, printer := newSaveManagerWithPrinter(t, mockGQL)

	result := <-saver.Save(
		context.Background(),
		&spb.ArtifactRecord{
			Name:     "ok-artifact",
			Type:     "dataset",
			Manifest: &spb.ArtifactManifest{Version: 1},
		},
		0,
		"",
	)

	require.NoError(t, result.Err)
	assert.Empty(t, failedSaveMessages(printer))
}

func TestSave_CancelledContextPrintsNoWarning(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchWithError(
		gqlmock.WithOpName("CreateArtifact"),
		context.Canceled,
	)
	saver, printer := newSaveManagerWithPrinter(t, mockGQL)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	result := <-saver.Save(
		ctx,
		&spb.ArtifactRecord{
			Name:     "aborted-artifact",
			Type:     "dataset",
			Manifest: &spb.ArtifactManifest{Version: 1},
		},
		0,
		"",
	)

	require.Error(t, result.Err)
	assert.Empty(t, printer.Read())
}
