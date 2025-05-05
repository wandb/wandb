package stream_test

import (
	"context"
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/golang/mock/gomock"
	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/mailbox"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runworktest"
	wbsettings "github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/stream"
	"github.com/wandb/wandb/core/internal/watchertest"
	"github.com/wandb/wandb/core/pkg/artifacts"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

const validUpsertBucketResponse = `{
	"upsertBucket": {
		"bucket": {
			"displayName": "FakeName",
			"project": {
				"name": "FakeProject",
				"entity": {
					"name": "FakeEntity"
				}
			}
		}
	}
}`

const validLinkArtifactResponse = `{
	"linkArtifact": { "versionIndex": 0 }
}`

func makeSender(client graphql.Client, resultChan chan *spb.Result) *stream.Sender {
	runWork := runworktest.New()
	logger := observability.NewNoOpLogger()
	settings := wbsettings.From(&spb.Settings{
		RunId:   &wrapperspb.StringValue{Value: "run1"},
		Console: &wrapperspb.StringValue{Value: "off"},
		ApiKey:  &wrapperspb.StringValue{Value: "test-api-key"},
	})
	backend := stream.NewBackend(logger, settings)
	fileStream := stream.NewFileStream(
		backend,
		logger,
		nil, // operations
		observability.NewPrinter(),
		settings,
		nil, // peeker
		"clientId",
	)
	fileTransferManager := stream.NewFileTransferManager(
		filetransfer.NewFileTransferStats(),
		logger,
		settings,
	)
	runfilesUploader := stream.NewRunfilesUploader(
		runWork,
		logger,
		nil, // operations
		settings,
		fileStream,
		fileTransferManager,
		watchertest.NewFakeWatcher(),
		client,
	)
	sender := stream.NewSender(
		stream.SenderParams{
			Logger:              logger,
			Settings:            settings,
			Backend:             backend,
			FileStream:          fileStream,
			FileTransferManager: fileTransferManager,
			RunfilesUploader:    runfilesUploader,
			OutChan:             resultChan,
			Mailbox:             mailbox.New(),
			GraphqlClient:       client,
			RunWork:             runWork,
			FeatureProvider: featurechecker.NewServerFeaturesCache(
				runWork.BeforeEndCtx(),
				nil,
				logger,
			),
		},
	)
	return sender
}

// Verify that project and entity are properly passed through to graphql
func TestSendRun(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("UpsertBucket"),
		validUpsertBucketResponse,
	)
	outChan := make(chan *spb.Result, 1)
	sender := makeSender(mockGQL, outChan)

	run := &spb.Record{
		RecordType: &spb.Record_Run{
			Run: &spb.RunRecord{
				Config: &spb.ConfigRecord{
					Update: []*spb.ConfigItem{
						{
							Key:       "_wandb",
							ValueJson: "{}",
						},
					},
				},
				Project: "testProject",
				Entity:  "testEntity",
			}},
		Control: &spb.Control{
			MailboxSlot: "junk",
		},
	}

	sender.SendRecord(run)
	<-outChan

	requests := mockGQL.AllRequests()
	assert.Len(t, requests, 1)
	gqlmock.AssertRequest(t,
		gqlmock.WithVariables(
			gqlmock.GQLVar("project", gomock.Eq("testProject")),
			gqlmock.GQLVar("entity", gomock.Eq("testEntity")),
		),
		requests[0])
}

// Verify that arguments are properly passed through to graphql
func TestSendLinkArtifact(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	outChan := make(chan *spb.Result, 1)
	sender := makeSender(mockGQL, outChan)

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
	sender.SendRecord(linkArtifact)
	<-outChan

	requests := mockGQL.AllRequests()
	assert.Len(t, requests, 1)
	gqlmock.AssertRequest(t,
		gqlmock.WithVariables(
			gqlmock.GQLVar("projectName", gomock.Eq("portfolioProject")),
			gqlmock.GQLVar("entityName", gomock.Eq("portfolioEntity")),
			gqlmock.GQLVar("artifactPortfolioName", gomock.Eq("portfolioName")),
			gqlmock.GQLVar("clientId", gomock.Eq(nil)),
			gqlmock.GQLVar("artifactId", gomock.Eq("serverId")),
		),
		requests[0])

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
	sender.SendRecord(linkArtifact)
	<-outChan

	requests = mockGQL.AllRequests()
	assert.Len(t, requests, 2)
	gqlmock.AssertRequest(t,
		gqlmock.WithVariables(
			gqlmock.GQLVar("projectName", gomock.Eq("portfolioProject")),
			gqlmock.GQLVar("entityName", gomock.Eq("portfolioEntity")),
			gqlmock.GQLVar("artifactPortfolioName", gomock.Eq("portfolioName")),
			gqlmock.GQLVar("clientId", gomock.Eq("clientId")),
			gqlmock.GQLVar("artifactId", gomock.Eq(nil)),
		),
		requests[1])

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
	sender.SendRecord(linkArtifact)
	<-outChan

	requests = mockGQL.AllRequests()
	assert.Len(t, requests, 3)
	gqlmock.AssertRequest(t,
		gqlmock.WithVariables(
			gqlmock.GQLVar("projectName", gomock.Eq("portfolioProject")),
			gqlmock.GQLVar("entityName", gomock.Eq("portfolioEntity")),
			gqlmock.GQLVar("artifactPortfolioName", gomock.Eq("portfolioName")),
			gqlmock.GQLVar("clientId", gomock.Eq(nil)),
			gqlmock.GQLVar("artifactId", gomock.Eq("serverId")),
		),
		requests[2])
}

func TestSendUseArtifact(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	sender := makeSender(mockGQL, make(chan *spb.Result, 1))

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
	sender.SendRecord(useArtifact)

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
	sender.SendRecord(useArtifact)
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
		isOldServer       bool
		errorMessage      string
	}{
		{"Link registry artifact with orgName updated server", "orgName", false, ""},
		{"Link registry artifact with orgName old server", "orgName", true, expectLinkArtifactFailure},
		{"Link registry artifact with orgEntity name updated server", "orgEntityName_123", false, ""},
		{"Link registry artifact with orgEntity name old server", "orgEntityName_123", true, ""},
		{"Link registry artifact with short hand path updated server", "", false, ""},
		{"Link registry artifact with short hand path old server", "", true, "unsupported"},
		{"Link with wrong org/orgEntity name with updated server", "potato", false, "update the target path"},
		{"Link with wrong org/orgEntity name with updated server", "potato", true, expectLinkArtifactFailure},
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

		// If user is on old server, we can't fetch the org entity name so just directly call link artifact
		numExpectedRequests := 3
		if tc.isOldServer {
			numExpectedRequests = 2
		}

		t.Run("Link registry artifact with orgName updated server", func(t *testing.T) {
			req := &spb.LinkArtifactRequest{
				ClientId:              "clientId123",
				PortfolioName:         "portfolioName",
				PortfolioEntity:       "entityName",
				PortfolioProject:      registryProject,
				PortfolioAliases:      nil,
				PortfolioOrganization: tc.inputOrganization,
			}

			var validTypeFieldsResponse string
			if tc.isOldServer {
				validTypeFieldsResponse = `{"TypeInfo": {"fields": []}}`
			} else {
				validTypeFieldsResponse = `{
		"TypeInfo": {
			"fields": [{"name": "orgEntity"}]
		}
	}`
			}
			mockGQL.StubMatchOnce(
				gqlmock.WithOpName("TypeFields"),
				validTypeFieldsResponse,
			)

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
				assert.Len(t, requests, numExpectedRequests)

				// Confirms that the request is incorrectly put into link artifact graphql request
				gqlmock.AssertRequest(t,
					gqlmock.WithVariables(
						gqlmock.GQLVar("projectName", gomock.Eq(registryProject)),
						// Here the entity name is not orgEntityName_123 and this will fail if actually called
						gqlmock.GQLVar("entityName", gomock.Not(gomock.Eq("orgEntityName_123"))),
						gqlmock.GQLVar("artifactPortfolioName", gomock.Eq("portfolioName")),
						gqlmock.GQLVar("clientId", gomock.Eq("clientId123")),
						gqlmock.GQLVar("artifactId", gomock.Nil()),
					),
					requests[numExpectedRequests-1])
			} else {
				// If no error, check that we are passing in the correct org entity name into linkArtifact
				assert.Empty(t, tc.errorMessage)
				assert.NoError(t, err)
				requests := mockGQL.AllRequests()
				assert.Len(t, requests, numExpectedRequests)

				gqlmock.AssertRequest(t,
					gqlmock.WithVariables(
						gqlmock.GQLVar("projectName", gomock.Eq(registryProject)),
						gqlmock.GQLVar("entityName", gomock.Eq("orgEntityName_123")),
						gqlmock.GQLVar("artifactPortfolioName", gomock.Eq("portfolioName")),
						gqlmock.GQLVar("clientId", gomock.Eq("clientId123")),
						gqlmock.GQLVar("artifactId", gomock.Nil()),
					),
					requests[numExpectedRequests-1])
			}
		})
	}
}
