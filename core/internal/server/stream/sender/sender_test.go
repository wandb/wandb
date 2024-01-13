package sender_test

import (
	"context"
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/golang/mock/gomock"
	"github.com/stretchr/testify/assert"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/coretest"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/server/stream/sender"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

func makeSender(client graphql.Client, resultChan chan *pb.Result) *sender.Sender {
	ctx, cancel := context.WithCancel(context.Background())
	logger := observability.NewNoOpLogger()
	sender := sender.NewSender(
		ctx,
		cancel,
		logger,
		&pb.Settings{
			RunId: &wrapperspb.StringValue{Value: "run1"},
		},
		sender.WithSenderFwdChannel(make(chan *pb.Record, 1)),
		sender.WithSenderOutChannel(resultChan),
	)
	sender.SetGraphqlClient(client)
	return sender
}

func TestSendRun(t *testing.T) {
	// Verify that project and entity are properly passed through to graphql
	to := coretest.MakeTestObject(t)
	defer to.TeardownTest()

	sender := makeSender(to.MockClient, make(chan *pb.Result, 1))

	run := &pb.Record{
		RecordType: &pb.Record_Run{
			Run: &pb.RunRecord{
				Config:  to.MakeConfig(),
				Project: "testProject",
				Entity:  "testEntity",
			}},
		Control: &pb.Control{
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

	sender := makeSender(to.MockClient, make(chan *pb.Result, 1))

	respEncode := &graphql.Response{
		Data: &gql.LinkArtifactResponse{
			LinkArtifact: &gql.LinkArtifactLinkArtifactLinkArtifactPayload{
				VersionIndex: coretest.IntPtr(0),
			},
		}}

	// 1. When both clientId and serverId are sent, serverId is used
	linkArtifact := &pb.Record{
		RecordType: &pb.Record_LinkArtifact{
			LinkArtifact: &pb.LinkArtifactRecord{
				ClientId:         "clientId",
				ServerId:         "serverId",
				PortfolioName:    "portfolioName",
				PortfolioEntity:  "portfolioEntity",
				PortfolioProject: "portfolioProject",
			}},
		Control: &pb.Control{
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
	linkArtifact = &pb.Record{
		RecordType: &pb.Record_LinkArtifact{
			LinkArtifact: &pb.LinkArtifactRecord{
				ClientId:         "clientId",
				ServerId:         "",
				PortfolioName:    "portfolioName",
				PortfolioEntity:  "portfolioEntity",
				PortfolioProject: "portfolioProject",
			}},
		Control: &pb.Control{
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
	linkArtifact = &pb.Record{
		RecordType: &pb.Record_LinkArtifact{
			LinkArtifact: &pb.LinkArtifactRecord{
				ClientId:         "",
				ServerId:         "serverId",
				PortfolioName:    "portfolioName",
				PortfolioEntity:  "portfolioEntity",
				PortfolioProject: "portfolioProject",
			}},
		Control: &pb.Control{
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
