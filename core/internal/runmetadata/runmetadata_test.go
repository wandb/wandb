package runmetadata_test

import (
	"context"
	"errors"
	"testing"

	"github.com/golang/mock/gomock"
	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runmetadata"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/waiting"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

// runRecord returns a Record with the run field set.
func runRecord(run *spb.RunRecord) *spb.Record {
	return &spb.Record{
		RecordType: &spb.Record_Run{
			Run: run,
		},
	}
}

// testParams returns metadata parameters with default values for testing.
func testParams() runmetadata.RunMetadataParams {
	return runmetadata.RunMetadataParams{
		DebounceDelay:   waiting.NoDelay(),
		Settings:        settings.New(),
		BeforeRunEndCtx: context.Background(),
		Operations:      nil,
		FeatureProvider: featurechecker.NewServerFeaturesCachePreloaded(
			map[spb.ServerFeature]featurechecker.Feature{},
		),
		GraphqlClientOrNil: nil,
		Logger:             observability.NewNoOpLogger(),
	}
}

// fakeUpsertBucketResponseJSON returns a fake UpsertBucket response.
func fakeUpsertBucketResponseJSON() string {
	return `{
		"upsertBucket": {
			"bucket": {
				"id": "storage ID",
				"name": "run ID",
				"displayName": "display name",
				"sweepName": "sweep ID",
				"project": {
					"name": "project name",
					"entity": {"name": "entity name"}
				}
			}
		}
	}`
}

func TestInitRun_MakesCorrectRequest(t *testing.T) {
	mockClient := gqlmock.NewMockClient()
	params := testParams()
	params.GraphqlClientOrNil = mockClient
	params.Settings = settings.From(&spb.Settings{
		Program: wrapperspb.String("program"),
	})
	mockClient.StubMatchOnce(
		gqlmock.WithOpName("UpsertBucket"),
		fakeUpsertBucketResponseJSON(),
	)

	metadata, _ := runmetadata.InitRun(
		runRecord(&spb.RunRecord{
			// In order of UpsertBucket parameters.
			StorageId:   "storage ID",
			RunId:       "run ID",
			Project:     "project name",
			Entity:      "entity name",
			RunGroup:    "group name",
			DisplayName: "display name",
			Notes:       "notes",
			Git: &spb.GitRepoRecord{
				Commit:    "commit",
				RemoteUrl: "remote URL", // repo parameter
			},
			Host:    "host",
			JobType: "job type",
			SweepId: "sweep ID",
			Tags:    []string{"tag1", "tag2"},
		}),
		params,
	)
	defer metadata.Finish()

	requests := mockClient.AllRequests()
	assert.Len(t, requests, 1)
	gqlmock.AssertVariables(
		t,
		requests[0],
		gqlmock.GQLVar("id", gomock.Eq("storage ID")),
		gqlmock.GQLVar("name", gomock.Eq("run ID")),
		gqlmock.GQLVar("project", gomock.Eq("project name")),
		gqlmock.GQLVar("entity", gomock.Eq("entity name")),
		gqlmock.GQLVar("groupName", gomock.Eq("group name")),
		gqlmock.GQLVar("displayName", gomock.Eq("display name")),
		gqlmock.GQLVar("notes", gomock.Eq("notes")),
		gqlmock.GQLVar("commit", gomock.Eq("commit")),
		gqlmock.GQLVar("host", gomock.Eq("host")),
		gqlmock.GQLVar("program", gomock.Eq("program")),
		gqlmock.GQLVar("repo", gomock.Eq("remote URL")),
		gqlmock.GQLVar("jobType", gomock.Eq("job type")),
		gqlmock.GQLVar("sweep", gomock.Eq("sweep ID")),
		gqlmock.GQLVar("tags", gomock.Eq([]any{"tag1", "tag2"})))
}

func TestInitRun_ReadsResponse(t *testing.T) {
	mockClient := gqlmock.NewMockClient()
	params := testParams()
	params.GraphqlClientOrNil = mockClient
	mockClient.StubMatchOnce(
		gqlmock.WithOpName("UpsertBucket"),
		`{
			"upsertBucket": {
				"bucket": {
					"id": "storage ID",
					"name": "run ID",
					"displayName": "display name",
					"sweepName": "sweep ID",
					"project": {
						"name": "project name",
						"entity": {"name": "entity name"}
					}
				}
			}
		}`,
	)

	metadata, err := runmetadata.InitRun(runRecord(&spb.RunRecord{}), params)
	defer metadata.Finish()

	run := &spb.RunRecord{}
	metadata.FillRunRecord(run)
	assert.Nil(t, err)
	assert.Equal(t, "storage ID", run.StorageId)
	assert.Equal(t, "run ID", run.RunId)
	assert.Equal(t, "display name", run.DisplayName)
	assert.Equal(t, "sweep ID", run.SweepId)
	assert.Equal(t, "project name", run.Project)
	assert.Equal(t, "entity name", run.Entity)
}

func TestInitRun_UpsertError(t *testing.T) {
	mockClient := gqlmock.NewMockClient()
	params := testParams()
	params.GraphqlClientOrNil = mockClient
	mockClient.StubMatchWithError(
		gqlmock.WithOpName("UpsertBucket"),
		errors.New("test error"),
	)

	metadata, err := runmetadata.InitRun(runRecord(&spb.RunRecord{}), params)

	assert.Nil(t, metadata)
	assert.ErrorContains(t, err, "test error")
}

func TestInitRun_Offline(t *testing.T) {
	params := testParams()
	params.GraphqlClientOrNil = nil

	metadata, err := runmetadata.InitRun(runRecord(&spb.RunRecord{}), params)
	defer metadata.Finish()

	assert.Nil(t, err)
	assert.NotNil(t, metadata)
}
