package server_test

import (
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/golang/mock/gomock"
	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/mailbox"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runworktest"
	wbsettings "github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/watchertest"
	"github.com/wandb/wandb/core/pkg/server"
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

func makeSender(client graphql.Client, recordChan chan *spb.Record, resultChan chan *spb.Result) *server.Sender {
	runWork := runworktest.New()
	logger := observability.NewNoOpLogger()
	settings := wbsettings.From(&spb.Settings{
		RunId:   &wrapperspb.StringValue{Value: "run1"},
		Console: &wrapperspb.StringValue{Value: "off"},
		ApiKey:  &wrapperspb.StringValue{Value: "test-api-key"},
	})
	backend := server.NewBackend(logger, settings)
	fileStream := server.NewFileStream(
		backend, logger, observability.NewPrinter(), settings, nil)
	fileTransferManager := server.NewFileTransferManager(
		filetransfer.NewFileTransferStats(),
		logger,
		settings,
	)
	runfilesUploader := server.NewRunfilesUploader(
		runWork,
		logger,
		settings,
		fileStream,
		fileTransferManager,
		watchertest.NewFakeWatcher(),
		client,
	)
	sender := server.NewSender(
		runWork,
		server.SenderParams{
			Logger:              logger,
			Settings:            settings,
			Backend:             backend,
			FileStream:          fileStream,
			FileTransferManager: fileTransferManager,
			RunfilesUploader:    runfilesUploader,
			OutChan:             resultChan,
			Mailbox:             mailbox.New(),
			GraphqlClient:       client,
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
	sender := makeSender(mockGQL, make(chan *spb.Record, 1), outChan)

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
	sender := makeSender(mockGQL, make(chan *spb.Record, 1), outChan)

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
	sender := makeSender(mockGQL, make(chan *spb.Record, 1), make(chan *spb.Result, 1))

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
