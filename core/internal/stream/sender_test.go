package stream_test

import (
	"context"
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/mailbox"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/runupserter"
	"github.com/wandb/wandb/core/internal/runupsertertest"
	"github.com/wandb/wandb/core/internal/runworktest"
	wbsettings "github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/stream"
	"github.com/wandb/wandb/core/internal/watchertest"
	"github.com/wandb/wandb/core/pkg/artifacts"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const validLinkArtifactResponse = `{
	"linkArtifact": { "versionIndex": 0 }
}`

type testFixtures struct {
	Sender    *stream.Sender
	RunHandle *runhandle.RunHandle
	Settings  *wbsettings.Settings
	Logger    *observability.CoreLogger
}

func makeSender(t *testing.T, client graphql.Client) testFixtures {
	return makeSenderWithMode(t, client, false /*shared*/)
}

func makeSenderWithMode(t *testing.T, client graphql.Client, shared bool) testFixtures {
	t.Helper()
	runWork := runworktest.New()
	logger := observabilitytest.NewTestLogger(t)
	settings := wbsettings.From(&spb.Settings{
		RunId:   &wrapperspb.StringValue{Value: "run1"},
		Console: &wrapperspb.StringValue{Value: "off"},
		ApiKey:  &wrapperspb.StringValue{Value: "test-api-key"},
		XShared: &wrapperspb.BoolValue{Value: shared},
	})
	baseURL := stream.BaseURLFromSettings(logger, settings)
	credentialProvider := stream.CredentialsFromSettings(logger, settings)
	fileStreamFactory := &filestream.FileStreamFactory{
		Logger:   logger,
		Printer:  observability.NewPrinter(0),
		Settings: settings,
	}
	fileTransferManager := stream.NewFileTransferManager(
		baseURL,
		filetransfer.NewFileTransferStats(),
		logger,
		settings,
	)
	runfilesUploaderFactory := &runfiles.UploaderFactory{
		FileTransfer: fileTransferManager,
		FileWatcher:  watchertest.NewFakeWatcher(),
		GraphQL:      client,
		Logger:       logger,
		Settings:     settings,
	}
	runHandle := runhandle.New()

	senderFactory := stream.SenderFactory{
		BaseURL:                 baseURL,
		CredentialProvider:      credentialProvider,
		Logger:                  logger,
		Settings:                settings,
		FileStreamFactory:       fileStreamFactory,
		FileTransferManager:     fileTransferManager,
		RunfilesUploaderFactory: runfilesUploaderFactory,
		Mailbox:                 mailbox.New(),
		GraphqlClient:           client,
		FeatureProvider:         featurechecker.New(nil, logger),
		RunHandle:               runHandle,
	}
	return testFixtures{
		Sender:    senderFactory.New(runWork),
		RunHandle: runHandle,
		Settings:  settings,
		Logger:    logger,
	}
}

func TestSendHistory_AssignsMissingStep(t *testing.T) {
	x := makeSender(t, gqlmock.NewMockClient())

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{{
			NestedKey: []string{"loss"},
			ValueJson: "1.23",
		}},
	}

	x.Sender.SendRecord(&spb.Record{
		RecordType: &spb.Record_History{History: history},
	}, nil)

	assert.Equal(t, []*spb.HistoryItem{
		{NestedKey: []string{"loss"}, ValueJson: "1.23"},
		{NestedKey: []string{"_step"}, ValueJson: "0"},
	}, history.Item)
	assert.Equal(t, int64(0), history.GetStep().GetNum())
}

func TestSendHistory_PreservesExistingStep(t *testing.T) {
	x := makeSender(t, gqlmock.NewMockClient())

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			{NestedKey: []string{"loss"}, ValueJson: "1.23"},
			{NestedKey: []string{"_step"}, ValueJson: "7"},
		},
	}

	x.Sender.SendRecord(&spb.Record{
		RecordType: &spb.Record_History{History: history},
	}, nil)

	assert.Equal(t, []*spb.HistoryItem{
		{NestedKey: []string{"loss"}, ValueJson: "1.23"},
		{NestedKey: []string{"_step"}, ValueJson: "7"},
	}, history.Item)
}

func TestSendHistory_RewritesStepBelowStartingStep(t *testing.T) {
	x := makeSender(t, gqlmock.NewMockClient())

	upserter := runupsertertest.NewOfflineUpserter(t)
	upserter.Update(&spb.RunRecord{StartingStep: 2})
	require.NoError(t, x.RunHandle.Init(upserter))
	defer upserter.Finish()

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			{NestedKey: []string{"loss"}, ValueJson: "0.6"},
			{NestedKey: []string{"_step"}, ValueJson: "0"},
		},
	}

	x.Sender.SendRecord(&spb.Record{
		RecordType: &spb.Record_History{History: history},
	}, nil)

	assert.Equal(t, "2", history.Item[1].ValueJson)
}

// staleResumeStatusResponse mimics RunResumeStatus after syncing an offline
// segment that logged two history rows but left summary _step at 0.
const staleResumeStatusResponse = `{
	"model": {
		"bucket": {
			"name": "run1",
			"id": "storage-id",
			"historyLineCount": 2,
			"eventsLineCount": 0,
			"logLineCount": 0,
			"historyTail": "[\"{\\\"_step\\\":0,\\\"loss\\\":0.9}\", \"{\\\"_step\\\":1,\\\"loss\\\":0.7}\"]",
			"summaryMetrics": "{\"loss\": 0.9, \"_step\": 0}",
			"config": "{}",
			"eventsTail": "[]",
			"wandbConfig": "{\"t\": 1}"
		}
	}
}`

func TestSendHistory_OfflineResumedSegmentRewritesSteps(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunResumeStatus"),
		staleResumeStatusResponse,
	)
	runupsertertest.StubUpsertBucket(t, mockGQL)

	x := makeSender(t, mockGQL)

	upserter, err := runupserter.InitRun(
		&spb.Record{RecordType: &spb.Record_Run{Run: &spb.RunRecord{
			Entity:     "entity",
			Project:    "project",
			RunId:      "run1",
			ResumeMode: "must",
		}}},
		runupserter.RunUpserterParams{
			GraphqlClientOrNil: mockGQL,
			BeforeRunEndCtx:    context.Background(),
			Logger:             x.Logger,
			ClientID:           "test-client",
			FeatureProvider:    featurechecker.New(nil, x.Logger),
			Settings:           wbsettings.From(&spb.Settings{}),
		},
	)
	require.NoError(t, err)
	defer upserter.Finish()
	require.NoError(t, x.RunHandle.Init(upserter))

	run := &spb.RunRecord{}
	upserter.FillRunRecord(run)
	assert.Equal(t, int64(2), run.StartingStep)

	for _, tc := range []struct {
		localStep string
		loss      string
		wantStep  string
	}{
		{localStep: "0", loss: "0.6", wantStep: "2"},
		{localStep: "1", loss: "0.4", wantStep: "3"},
	} {
		history := &spb.HistoryRecord{
			Item: []*spb.HistoryItem{
				{NestedKey: []string{"loss"}, ValueJson: tc.loss},
				{NestedKey: []string{"_step"}, ValueJson: tc.localStep},
			},
		}
		x.Sender.SendRecord(&spb.Record{
			RecordType: &spb.Record_History{History: history},
		}, nil)
		assert.Equal(t, tc.wantStep, historyStepValue(history))
	}
}

func historyStepValue(record *spb.HistoryRecord) string {
	for _, item := range record.Item {
		if item.GetKey() == "_step" ||
			(len(item.GetNestedKey()) == 1 && item.GetNestedKey()[0] == "_step") {
			return item.ValueJson
		}
	}
	return ""
}

func TestSendHistory_MaterializesRecordStep(t *testing.T) {
	x := makeSender(t, gqlmock.NewMockClient())

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{{
			NestedKey: []string{"loss"},
			ValueJson: "1.23",
		}},
		Step: &spb.HistoryStep{Num: 5},
	}

	x.Sender.SendRecord(&spb.Record{
		RecordType: &spb.Record_History{History: history},
	}, nil)

	assert.Equal(t, []*spb.HistoryItem{
		{NestedKey: []string{"loss"}, ValueJson: "1.23"},
		{NestedKey: []string{"_step"}, ValueJson: "5"},
	}, history.Item)
}

func TestSendHistory_DerivesSummaryStep(t *testing.T) {
	x := makeSender(t, gqlmock.NewMockClient())

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{{
			NestedKey: []string{"loss"},
			ValueJson: "1.23",
		}},
	}

	x.Sender.SendRecord(&spb.Record{
		RecordType: &spb.Record_History{History: history},
	}, nil)

	summary, err := x.Sender.SummaryForTest()
	require.NoError(t, err)

	var stepValue string
	for _, item := range summary {
		if item.GetKey() == "_step" {
			stepValue = item.GetValueJson()
		}
	}
	assert.Equal(t, "0", stepValue)
}

func TestSendHistory_SharedModeSkipsSummaryStep(t *testing.T) {
	x := makeSenderWithMode(t, gqlmock.NewMockClient(), true /*shared*/)

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{{
			NestedKey: []string{"loss"},
			ValueJson: "1.23",
		}},
	}

	x.Sender.SendRecord(&spb.Record{
		RecordType: &spb.Record_History{History: history},
	}, nil)

	summary, err := x.Sender.SummaryForTest()
	require.NoError(t, err)
	for _, item := range summary {
		assert.NotEqual(t, "_step", item.GetKey())
	}
}

func TestSendHistory_PreservesForwardedAggregation(t *testing.T) {
	x := makeSender(t, gqlmock.NewMockClient())

	// Simulate the handler forwarding a define_metric("acc", summary="max")
	// aggregation of 0.9, which the sender applies to its runSummary.
	x.Sender.SendRecord(&spb.Record{
		RecordType: &spb.Record_Summary{Summary: &spb.SummaryRecord{
			Update: []*spb.SummaryItem{{
				Key:       "acc",
				ValueJson: "0.9",
			}},
		}},
	}, nil)

	// A later history row logs a lower value; the sender must not re-derive
	// acc from raw history and clobber the forwarded max.
	x.Sender.SendRecord(&spb.Record{
		RecordType: &spb.Record_History{History: &spb.HistoryRecord{
			Item: []*spb.HistoryItem{{
				NestedKey: []string{"acc"},
				ValueJson: "0.4",
			}},
		}},
	}, nil)

	summary, err := x.Sender.SummaryForTest()
	require.NoError(t, err)

	var accValue, stepValue string
	for _, item := range summary {
		switch item.GetKey() {
		case "acc":
			accValue = item.GetValueJson()
		case "_step":
			stepValue = item.GetValueJson()
		}
	}
	assert.Equal(t, "0.9", accValue)
	assert.Equal(t, "0", stepValue)
}

func TestSendHistory_RebasedStepMaterializesSummaryStep(t *testing.T) {
	x := makeSender(t, gqlmock.NewMockClient())

	upserter := runupsertertest.NewOfflineUpserter(t)
	upserter.Update(&spb.RunRecord{StartingStep: 2})
	require.NoError(t, x.RunHandle.Init(upserter))
	defer upserter.Finish()

	// An offline-resumed row logged with a local step of 0 is rebased forward
	// to the run's starting step; the summary _step must track the rebased
	// value, not the stale local one.
	x.Sender.SendRecord(&spb.Record{
		RecordType: &spb.Record_History{History: &spb.HistoryRecord{
			Item: []*spb.HistoryItem{
				{NestedKey: []string{"loss"}, ValueJson: "0.6"},
				{NestedKey: []string{"_step"}, ValueJson: "0"},
			},
		}},
	}, nil)

	summary, err := x.Sender.SummaryForTest()
	require.NoError(t, err)

	var stepValue string
	for _, item := range summary {
		if item.GetKey() == "_step" {
			stepValue = item.GetValueJson()
		}
	}
	assert.Equal(t, "2", stepValue)
}

// Verify that arguments are properly passed through to graphql
func TestSendLinkArtifact(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	x := makeSender(t, mockGQL)

	// 1. When both clientId and serverId are sent, serverId is used
	linkArtifact := &spb.Record{
		RecordType: &spb.Record_Request{
			Request: &spb.Request{
				RequestType: &spb.Request_LinkArtifact{
					LinkArtifact: &spb.LinkArtifactRequest{
						ClientId:         "clientId",
						ServerId:         "serverId",
						PortfolioName:    "portfolioName",
						PortfolioEntity:  "portfolioEntity",
						PortfolioProject: "portfolioProject",
					},
				},
			},
		},
		Control: &spb.Control{
			MailboxSlot: "junk",
		},
	}

	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("LinkArtifact"),
		validLinkArtifactResponse,
	)
	request, outputs := runworktest.SimpleRequest(t, "test-id")
	x.Sender.SendRecord(linkArtifact, request)
	<-outputs

	requests := mockGQL.AllRequests()
	assert.Len(t, requests, 1)
	gqlmock.AssertVariables(t,
		requests[0],
		gqlmock.GQLVar("projectName", gomock.Eq("portfolioProject")),
		gqlmock.GQLVar("entityName", gomock.Eq("portfolioEntity")),
		gqlmock.GQLVar("artifactPortfolioName", gomock.Eq("portfolioName")),
		gqlmock.GQLVar("clientId", gomock.Eq(nil)),
		gqlmock.GQLVar("artifactId", gomock.Eq("serverId")))

	// 2. When only clientId is sent, clientId is used
	linkArtifact = &spb.Record{
		RecordType: &spb.Record_Request{
			Request: &spb.Request{
				RequestType: &spb.Request_LinkArtifact{
					LinkArtifact: &spb.LinkArtifactRequest{
						ClientId:         "clientId",
						ServerId:         "",
						PortfolioName:    "portfolioName",
						PortfolioEntity:  "portfolioEntity",
						PortfolioProject: "portfolioProject",
					},
				},
			},
		},
	}

	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("LinkArtifact"),
		validLinkArtifactResponse,
	)
	request, outputs = runworktest.SimpleRequest(t, "test-id")
	x.Sender.SendRecord(linkArtifact, request)
	<-outputs

	requests = mockGQL.AllRequests()
	assert.Len(t, requests, 2)
	gqlmock.AssertVariables(t,
		requests[1],
		gqlmock.GQLVar("projectName", gomock.Eq("portfolioProject")),
		gqlmock.GQLVar("entityName", gomock.Eq("portfolioEntity")),
		gqlmock.GQLVar("artifactPortfolioName", gomock.Eq("portfolioName")),
		gqlmock.GQLVar("clientId", gomock.Eq("clientId")),
		gqlmock.GQLVar("artifactId", gomock.Eq(nil)))

	// 3. When only serverId is sent, serverId is used
	linkArtifact = &spb.Record{
		RecordType: &spb.Record_Request{
			Request: &spb.Request{
				RequestType: &spb.Request_LinkArtifact{
					LinkArtifact: &spb.LinkArtifactRequest{
						ClientId:         "",
						ServerId:         "serverId",
						PortfolioName:    "portfolioName",
						PortfolioEntity:  "portfolioEntity",
						PortfolioProject: "portfolioProject",
					},
				},
			},
		},
	}

	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("LinkArtifact"),
		validLinkArtifactResponse,
	)
	request, outputs = runworktest.SimpleRequest(t, "test-id")
	x.Sender.SendRecord(linkArtifact, request)
	<-outputs

	requests = mockGQL.AllRequests()
	assert.Len(t, requests, 3)
	gqlmock.AssertVariables(t,
		requests[2],
		gqlmock.GQLVar("projectName", gomock.Eq("portfolioProject")),
		gqlmock.GQLVar("entityName", gomock.Eq("portfolioEntity")),
		gqlmock.GQLVar("artifactPortfolioName", gomock.Eq("portfolioName")),
		gqlmock.GQLVar("clientId", gomock.Eq(nil)),
		gqlmock.GQLVar("artifactId", gomock.Eq("serverId")))
}

func TestSendUseArtifact(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	x := makeSender(t, mockGQL)

	useArtifact := &spb.Record{
		RecordType: &spb.Record_UseArtifact{
			UseArtifact: &spb.UseArtifactRecord{
				Id:      "artifactId",
				Type:    "job",
				Name:    "artifactName",
				Partial: nil,
			},
		},
	}
	// verify doesn't panic if used job artifact
	x.Sender.SendRecord(useArtifact, nil)

	// verify doesn't panic if partial job is broken
	useArtifact = &spb.Record{
		RecordType: &spb.Record_UseArtifact{
			UseArtifact: &spb.UseArtifactRecord{
				Id:   "artifactId",
				Type: "job",
				Name: "artifactName",
				Partial: &spb.PartialJobArtifact{
					JobName: "jobName",
					SourceInfo: &spb.JobSource{
						SourceType: "repo",
						Source: &spb.Source{
							Git: &spb.GitSource{
								GitInfo: &spb.GitInfo{
									Commit: "commit",
									Remote: "remote",
								},
							},
						},
					},
				},
			},
		},
	}
	x.Sender.SendRecord(useArtifact, nil)
}

var validFetchOrgEntityFromEntityResponse = `{
	"entity": {
		"organization": {
			"name": "orgName",
			"orgEntity": {
				"name": "orgEntityName_123"
			}
		}
	}
}`

func TestLinkRegistryArtifact(t *testing.T) {
	registryProject := artifacts.RegistryProjectPrefix + "projectName"
	expectLinkArtifactFailure := "expect link artifact to fail, wrong org entity"

	testCases := []struct {
		name              string
		inputOrganization string
		errorMessage      string
	}{
		{"Link registry artifact with orgName", "orgName", ""},
		{
			"Link registry artifact with orgEntity name",
			"orgEntityName_123",
			"",
		},
		{"Link registry artifact with short hand path", "", ""},
		{
			"Link with wrong org/orgEntity name",
			"potato",
			"update the target path",
		},
	}
	for _, tc := range testCases {
		mockGQL := gqlmock.NewMockClient()

		newLinker := func(req *spb.LinkArtifactRequest) *artifacts.ArtifactLinker {
			return &artifacts.ArtifactLinker{
				Ctx:           context.Background(),
				LinkArtifact:  req,
				GraphqlClient: mockGQL,
			}
		}

		t.Run("Link registry artifact with orgName", func(t *testing.T) {
			req := &spb.LinkArtifactRequest{
				ClientId:              "clientId123",
				PortfolioName:         "portfolioName",
				PortfolioEntity:       "entityName",
				PortfolioProject:      registryProject,
				PortfolioAliases:      nil,
				PortfolioOrganization: tc.inputOrganization,
			}

			mockGQL.StubMatchOnce(
				gqlmock.WithOpName("LinkArtifact"),
				validLinkArtifactResponse,
			)

			mockGQL.StubMatchOnce(
				gqlmock.WithOpName("FetchOrgEntityFromEntity"),
				validFetchOrgEntityFromEntityResponse,
			)

			linker := newLinker(req)
			_, err := linker.Link()
			if err != nil {
				assert.NotEmpty(t, tc.errorMessage)
				assert.ErrorContainsf(t, err, tc.errorMessage,
					"Expected error containing: %s", tc.errorMessage)
				return
			}

			// This error is not triggered by Link() because its linkArtifact that fails
			// and we aren't actually calling it.
			// Here we are checking that the org entity being passed into linkArtifact
			// is wrong so we know the query will fail.
			if tc.errorMessage == expectLinkArtifactFailure {
				requests := mockGQL.AllRequests()
				assert.Len(t, requests, 2)

				// Confirms that the request is incorrectly put into link artifact graphql request
				gqlmock.AssertVariables(t,
					requests[1],
					gqlmock.GQLVar("projectName", gomock.Eq(registryProject)),
					// Here the entity name is not orgEntityName_123 and this will fail if actually called
					gqlmock.GQLVar("entityName", gomock.Not(gomock.Eq("orgEntityName_123"))),
					gqlmock.GQLVar("artifactPortfolioName", gomock.Eq("portfolioName")),
					gqlmock.GQLVar("clientId", gomock.Eq("clientId123")),
					gqlmock.GQLVar("artifactId", gomock.Nil()))
			} else {
				// If no error, check that we are passing in the correct org entity name into linkArtifact
				assert.Empty(t, tc.errorMessage)
				assert.NoError(t, err)
				requests := mockGQL.AllRequests()
				assert.Len(t, requests, 2)

				gqlmock.AssertVariables(t,
					requests[1],
					gqlmock.GQLVar("projectName", gomock.Eq(registryProject)),
					gqlmock.GQLVar("entityName", gomock.Eq("orgEntityName_123")),
					gqlmock.GQLVar("artifactPortfolioName", gomock.Eq("portfolioName")),
					gqlmock.GQLVar("clientId", gomock.Eq("clientId123")),
					gqlmock.GQLVar("artifactId", gomock.Nil()))
			}
		})
	}
}
