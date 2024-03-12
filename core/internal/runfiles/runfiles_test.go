package runfiles_test

import (
	"context"
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/filetransfertest"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/gqlmock"
	. "github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/runfilestest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

func stubCreateRunFiles(mockGQLClient *gqlmock.MockClient) {
	// TODO: This should stub using a custom matcher.
	mockGQLClient.StubOnce(
		func(client graphql.Client) {
			_, _ = gql.CreateRunFiles(
				context.Background(),
				client,
				"test-entity",
				"test-project",
				"test-run",
				[]string{"the/files/directory/file.txt"},
			)
		},
		`"createRunFiles": {
			"runID": "test-run",
			"uploadHeaders": ["Header1:Value1", "Header2:Value2"],
			"files": [
				{
					"name": "test-file",
					"uploadUrl": "https://example.com/test-file",
				}
			]
		}`,
	)
}

func TestProcess_Now_UploadsImmediately(t *testing.T) {
	t.Skip("Not implemented yet")

	fakeFileTransfer := filetransfertest.NewFakeFileTransferManager()
	mockGQLClient := gqlmock.NewMockClient()
	stubCreateRunFiles(mockGQLClient)
	manager := NewManager(runfilestest.WithTestDefaults(ManagerParams{
		GraphQL:      mockGQLClient,
		FileTransfer: fakeFileTransfer,
	}))

	manager.ProcessRecord(&service.FilesRecord{
		Files: []*service.FilesItem{
			{Path: "file.txt", Policy: service.FilesItem_NOW},
		},
	})
	manager.Finish() // No flush!

	assert.Len(t, fakeFileTransfer.Tasks(), 1)
}

func TestProcess_End_UploadsAtEnd(t *testing.T) {
	t.Skip("Not implemented yet")

	fakeFileTransfer := filetransfertest.NewFakeFileTransferManager()
	mockGQLClient := gqlmock.NewMockClient()
	stubCreateRunFiles(mockGQLClient)
	manager := NewManager(runfilestest.WithTestDefaults(ManagerParams{
		GraphQL:      mockGQLClient,
		FileTransfer: fakeFileTransfer,
	}))

	manager.ProcessRecord(&service.FilesRecord{
		Files: []*service.FilesItem{
			{Path: "file.txt", Policy: service.FilesItem_END},
		},
	})
	manager.Flush()
	manager.Finish()

	assert.Len(t, fakeFileTransfer.Tasks(), 1)
}

func TestProcess_UploadsUsingGraphQLResponse(t *testing.T) {
	t.Skip("Not implemented yet")

	fakeFileTransfer := filetransfertest.NewFakeFileTransferManager()
	mockGQLClient := gqlmock.NewMockClient()
	mockGQLClient.StubOnce(
		func(client graphql.Client) {
			_, _ = gql.CreateRunFiles(
				context.Background(),
				client,
				"test-entity",
				"test-project",
				"test-run",
				[]string{"the/files/directory/file.txt"},
			)
		},
		`"createRunFiles": {
			"runID": "test-run",
			"uploadHeaders": ["Header1:Value1", "Header2:Value2"],
			"files": [
				{
					"name": "test-file",
					"uploadUrl": "https://example.com/test-file",
				}
			]
		}`,
	)
	manager := NewManager(runfilestest.WithTestDefaults(ManagerParams{
		GraphQL:      mockGQLClient,
		FileTransfer: fakeFileTransfer,
		Settings: settings.From(&service.Settings{
			FilesDir: &wrapperspb.StringValue{
				Value: "the/files/directory",
			},
		}),
	}))

	manager.ProcessRecord(&service.FilesRecord{
		Files: []*service.FilesItem{
			{Path: "file.txt", Policy: service.FilesItem_NOW},
		},
	})
	manager.Finish()

	uploadTasks := fakeFileTransfer.Tasks()
	assert.Len(t, uploadTasks, 1)
	assert.Equal(t,
		&filetransfer.Task{
			Type:    filetransfer.UploadTask,
			Path:    "the/files/directory/file.txt",
			Name:    "test-file",
			Url:     "https://example.com/test-file",
			Headers: []string{"Header1:Value1", "Header2:Value2"},
		},
		uploadTasks[0].Path)
}
