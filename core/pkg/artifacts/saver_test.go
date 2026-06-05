package artifacts

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
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
		true,
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

func TestManifestStagingDir_UsesStagingSubdir(t *testing.T) {
	staging := t.TempDir()
	as := &ArtifactSaver{stagingDir: staging}

	dir, err := as.manifestStagingDir()

	assert.NoError(t, err)
	assert.Equal(t, filepath.Join(staging, "artifact_manifests"), dir)
	assert.DirExists(t, dir)
}

func TestManifestStagingDir_EmptyWhenNoStagingDir(t *testing.T) {
	as := &ArtifactSaver{stagingDir: ""}

	dir, err := as.manifestStagingDir()

	assert.NoError(t, err)
	assert.Empty(t, dir)
}

func TestManifestStagingDir_ErrorsWhenStagingDirUnwritable(t *testing.T) {
	// A file (not a dir) where the staging dir should be: MkdirAll fails.
	parent := t.TempDir()
	notADir := filepath.Join(parent, "staging-is-a-file")
	assert.NoError(t, os.WriteFile(notADir, []byte("x"), 0o600))
	as := &ArtifactSaver{stagingDir: notADir}

	_, err := as.manifestStagingDir()

	assert.Error(t, err)
}
