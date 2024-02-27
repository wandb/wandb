package server_test

import (
	"context"
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/golang/mock/gomock"
	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/coretest"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/server"
	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

func makeSender(client graphql.Client, resultChan chan *service.Result) *server.Sender {
	ctx, cancel := context.WithCancel(context.Background())
	logger := observability.NewNoOpLogger()
	sender := server.NewSender(
		ctx,
		cancel,
		logger,
		&service.Settings{
			RunId: &wrapperspb.StringValue{Value: "run1"},
		},
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
	// <-sender.GetOutboundChannel()

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
	// <-sender.GetOutboundChannel()

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
	// <-sender.GetOutboundChannel()
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
