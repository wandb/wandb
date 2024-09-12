package server_test

import (
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/golang/mock/gomock"
	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/mailbox"
	"github.com/wandb/wandb/core/internal/runworktest"
	wbsettings "github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/watchertest"
	"github.com/wandb/wandb/core/pkg/observability"
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

const validCreateArtifactResponse = `{
	"createArtifact": {
		"artifact": {
			"id": "artifact-id"
		}
	}
}`

func makeSender(client graphql.Client, recordChan chan *spb.Record, resultChan chan *spb.Result) *server.Sender {
	runWork := runworktest.New()
	logger := observability.NewNoOpLogger()
	settings := wbsettings.From(&spb.Settings{
		RunId: &wrapperspb.StringValue{Value: "run1"},
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

// Verify that arguments are properly passed through to graphql
func TestSendArtifact(t *testing.T) {
	tests := []struct {
		name string
		tags []string
	}{
		{
			name: "Received non-empty tags",
			tags: []string{"test-tag1", "test-tag2"},
		},
		{
			name: "Received empty tags",
			tags: []string{},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {

			mockGQL := gqlmock.NewMockClient()
			mockGQL.StubMatchOnce(
				gqlmock.WithOpName("InputFields"),
				`{"TypeInfo": {"inputFields": [{"name": "tags"}]}}`,
			)
			mockGQL.StubMatchOnce(
				gqlmock.WithOpName("CreateArtifact"),
				validCreateArtifactResponse,
			)
			sender := makeSender(mockGQL, make(chan *spb.Record, 1), make(chan *spb.Result, 1))

			// 1. When both clientId and serverId are sent, serverId is used
			artifact := &spb.Record{
				RecordType: &spb.Record_Artifact{
					Artifact: &spb.ArtifactRecord{
						RunId:   "test-run-id",
						Project: "test-project",
						Entity:  "test-entity",
						Type:    "test-type",
						Name:    "test-artifact",
						Digest:  "test-digest",
						Aliases: []string{"latest"},
						Tags:    tt.tags,
						Manifest: &spb.ArtifactManifest{
							Version:       1,
							StoragePolicy: "wandb-storage-policy-v1",
							Contents: []*spb.ArtifactManifestEntry{{
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

			sender.SendRecord(artifact)

			requests := mockGQL.AllRequests()
			assert.LessOrEqual(t, len(requests), 2)

			// We may have had an introspection request to check for server compatibility, but
			// CreateArtifact should still be the last request
			createArtifactRequest := requests[len(requests)-1]

			// Tags should only have been included in the request if the server supports it
			var expectedTagsValue gomock.Matcher
			if len(tt.tags) > 0 {
				expectedTagsValue = gomock.Len(len(tt.tags))
			} else {
				expectedTagsValue = gomock.Nil()
			}

			gqlmock.AssertRequest(t,
				gqlmock.WithVariables(
					gqlmock.GQLVar("input.entityName", gomock.Eq("test-entity")),
					gqlmock.GQLVar("input.tags", expectedTagsValue),
				),
				createArtifactRequest)
		})
	}
}
