package server_test

import (
	"context"
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/golang/mock/gomock"
	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/coretest"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/gql"
	wbsettings "github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/server"
	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

func makeSender(client graphql.Client, resultChan chan *service.Result) *server.Sender {
	ctx, cancel := context.WithCancel(context.Background())
	logger := observability.NewNoOpLogger()
	settings := wbsettings.From(&service.Settings{
		RunId: &wrapperspb.StringValue{Value: "run1"},
	})
	backend := server.NewBackend(logger, settings)
	fileStream := server.NewFileStream(backend, logger, settings)
	fileTransferManager := server.NewFileTransferManager(
		fileStream,
		filetransfer.NewFileTransferStats(),
		logger,
		settings,
	)
	sender := server.NewSender(
		ctx,
		cancel,
		backend,
		fileStream,
		fileTransferManager,
		logger,
		settings.Proto,
		server.WithSenderFwdChannel(make(chan *service.Record, 1)),
		server.WithSenderOutChannel(resultChan),
	)
	sender.SetGraphqlClient(client)
	return sender
}

func TestSendRun(t *testing.T) {
	// Verify that project and entity are properly passed through to graphql
	to := coretest.MakeTestObject(t)
	defer to.TeardownTest()

	sender := makeSender(to.MockClient, make(chan *service.Result, 1))

	run := &service.Record{
		RecordType: &service.Record_Run{
			Run: &service.RunRecord{
				Config:  to.MakeConfig(),
				Project: "testProject",
				Entity:  "testEntity",
			}},
		Control: &service.Control{
			MailboxSlot: "junk",
		},
	}

	respEncode := &graphql.Response{
		Data: &gql.UpsertBucketResponse{
			UpsertBucket: &gql.UpsertBucketUpsertBucketUpsertBucketPayload{
				Bucket: &gql.UpsertBucketUpsertBucketUpsertBucketPayloadBucketRun{
					DisplayName: coretest.StrPtr("FakeName"),
					Project: &gql.UpsertBucketUpsertBucketUpsertBucketPayloadBucketRunProject{
						Name: "FakeProject",
						Entity: gql.UpsertBucketUpsertBucketUpsertBucketPayloadBucketRunProjectEntity{
							Name: "FakeEntity",
						},
					},
				},
			},
		},
	}

	to.MockClient.EXPECT().MakeRequest(
		gomock.Any(), // context.Context
		gomock.Any(), // *graphql.Request
		gomock.Any(), // *graphql.Response
	).Return(nil).Do(coretest.InjectResponse(
		respEncode,
		func(vars coretest.RequestVars) {
			assert.Equal(t, "testEntity", vars["entity"])
			assert.Equal(t, "testProject", vars["project"])
		},
	))

	sender.SendRecord(run)
	<-sender.GetOutboundChannel()
}

func TestSendLinkArtifact(t *testing.T) {
	// Verify that arguments are properly passed through to graphql
	to := coretest.MakeTestObject(t)
	defer to.TeardownTest()

	sender := makeSender(to.MockClient, make(chan *service.Result, 1))

	respEncode := &graphql.Response{
		Data: &gql.LinkArtifactResponse{
			LinkArtifact: &gql.LinkArtifactLinkArtifactLinkArtifactPayload{
				VersionIndex: coretest.IntPtr(0),
			},
		}}

	// 1. When both clientId and serverId are sent, serverId is used
	linkArtifact := &service.Record{
		RecordType: &service.Record_LinkArtifact{
			LinkArtifact: &service.LinkArtifactRecord{
				ClientId:         "clientId",
				ServerId:         "serverId",
				PortfolioName:    "portfolioName",
				PortfolioEntity:  "portfolioEntity",
				PortfolioProject: "portfolioProject",
			}},
		Control: &service.Control{
			MailboxSlot: "junk",
		},
	}

	to.MockClient.EXPECT().MakeRequest(
		gomock.Any(), // context.Context
		gomock.Any(), // *graphql.Request
		gomock.Any(), // *graphql.Response
	).Return(nil).Do(coretest.InjectResponse(
		respEncode,
		func(vars coretest.RequestVars) {
			assert.Equal(t, "portfolioProject", vars["projectName"])
			assert.Equal(t, "portfolioEntity", vars["entityName"])
			assert.Equal(t, "portfolioName", vars["artifactPortfolioName"])
			assert.Nil(t, vars["clientId"])
			assert.Equal(t, "serverId", vars["artifactId"])
		},
	))

	sender.SendRecord(linkArtifact)
	<-sender.GetOutboundChannel()

	// 2. When only clientId is sent, clientId is used
	linkArtifact = &service.Record{
		RecordType: &service.Record_LinkArtifact{
			LinkArtifact: &service.LinkArtifactRecord{
				ClientId:         "clientId",
				ServerId:         "",
				PortfolioName:    "portfolioName",
				PortfolioEntity:  "portfolioEntity",
				PortfolioProject: "portfolioProject",
			}},
		Control: &service.Control{
			MailboxSlot: "junk",
		},
	}

	to.MockClient.EXPECT().MakeRequest(
		gomock.Any(), // context.Context
		gomock.Any(), // *graphql.Request
		gomock.Any(), // *graphql.Response
	).Return(nil).Do(coretest.InjectResponse(
		respEncode,
		func(vars coretest.RequestVars) {
			assert.Equal(t, "portfolioProject", vars["projectName"])
			assert.Equal(t, "portfolioEntity", vars["entityName"])
			assert.Equal(t, "portfolioName", vars["artifactPortfolioName"])
			assert.Equal(t, "clientId", vars["clientId"])
			assert.Nil(t, vars["artifactId"])
		},
	))

	sender.SendRecord(linkArtifact)
	<-sender.GetOutboundChannel()

	// 2. When only serverId is sent, serverId is used
	linkArtifact = &service.Record{
		RecordType: &service.Record_LinkArtifact{
			LinkArtifact: &service.LinkArtifactRecord{
				ClientId:         "",
				ServerId:         "serverId",
				PortfolioName:    "portfolioName",
				PortfolioEntity:  "portfolioEntity",
				PortfolioProject: "portfolioProject",
			}},
		Control: &service.Control{
			MailboxSlot: "junk",
		},
	}

	to.MockClient.EXPECT().MakeRequest(
		gomock.Any(), // context.Context
		gomock.Any(), // *graphql.Request
		gomock.Any(), // *graphql.Response
	).Return(nil).Do(coretest.InjectResponse(
		respEncode,
		func(vars coretest.RequestVars) {
			assert.Equal(t, "portfolioProject", vars["projectName"])
			assert.Equal(t, "portfolioEntity", vars["entityName"])
			assert.Equal(t, "portfolioName", vars["artifactPortfolioName"])
			assert.Nil(t, vars["clientId"])
			assert.Equal(t, "serverId", vars["artifactId"])
		},
	))

	sender.SendRecord(linkArtifact)
	<-sender.GetOutboundChannel()
}

func TestSendUseArtifact(t *testing.T) {
	to := coretest.MakeTestObject(t)
	defer to.TeardownTest()

	sender := makeSender(to.MockClient, make(chan *service.Result, 1))

	useArtifact := &service.Record{
		RecordType: &service.Record_UseArtifact{
			UseArtifact: &service.UseArtifactRecord{
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
	useArtifact = &service.Record{
		RecordType: &service.Record_UseArtifact{
			UseArtifact: &service.UseArtifactRecord{
				Id:   "artifactId",
				Type: "job",
				Name: "artifactName",
				Partial: &service.PartialJobArtifact{
					JobName: "jobName",
					SourceInfo: &service.JobSource{
						SourceType: "repo",
						Source: &service.Source{
							Git: &service.GitSource{
								GitInfo: &service.GitInfo{
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

func TestSendArtifact(t *testing.T) {
	// Verify that arguments are properly passed through to graphql
	to := coretest.MakeTestObject(t)
	defer to.TeardownTest()

	sender := makeSender(to.MockClient, make(chan *service.Result, 1))

	// 1. When both clientId and serverId are sent, serverId is used
	artifact := &service.Record{
		RecordType: &service.Record_Artifact{
			Artifact: &service.ArtifactRecord{
				RunId:   "test-run-id",
				Project: "test-project",
				Entity:  "test-entity",
				Type:    "test-type",
				Name:    "test-artifact",
				Digest:  "test-digest",
				Aliases: []string{"latest"},
				Manifest: &service.ArtifactManifest{
					Version:       1,
					StoragePolicy: "wandb-storage-policy-v1",
					Contents: []*service.ArtifactManifestEntry{{
						Path:      "test1",
						Digest:    "test1-digest",
						Size:      1,
						LocalPath: "/test/local/path",
					},
					},
				},
				Finalize:         true,
				ClientId:         "client-id",
				SequenceClientId: "sequence-client-id",
			}},
	}
	createArtifactRespEncode := &graphql.Response{
		Data: &gql.CreateArtifactResponse{
			CreateArtifact: &gql.CreateArtifactCreateArtifactCreateArtifactPayload{
				Artifact: gql.CreateArtifactCreateArtifactCreateArtifactPayloadArtifact{
					Id: "artifact-id",
				},
			},
		}}
	to.MockClient.EXPECT().MakeRequest(
		gomock.Any(), // context.Context
		gomock.Any(), // *graphql.Request
		gomock.Any(), // *graphql.Response
	).Return(nil).Do(coretest.InjectResponse(
		createArtifactRespEncode,
		func(vars coretest.RequestVars) {
			assert.Equal(t, "test-entity", vars["entityName"])
		},
	))
	sender.SendRecord(artifact)
}
