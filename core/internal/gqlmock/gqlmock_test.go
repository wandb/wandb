package gqlmock_test

import (
	"context"
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/gqlmock"
)

func TestUnstubbedRequest_ErrorContainsRequest(t *testing.T) {
	mock := gqlmock.NewMockClient()

	err := mock.MakeRequest(
		context.Background(),
		&graphql.Request{
			Query: "hero { name }",
			Variables: map[string]string{
				"x": "y",
			},
		},
		nil,
	)

	assert.ErrorContains(t, err, "hero { name }")
	assert.ErrorContains(t, err, "map[x:y]")
}

func TestStubbedRequest_UsesStub(t *testing.T) {
	mock := gqlmock.NewMockClient()
	mock.StubOnce(
		func(client graphql.Client) {
			_, _ = gql.CreateRunFiles(
				context.Background(),
				client,
				"entity",
				"project",
				"run",
				[]string{},
			)
		},
		`{
			"createRunFiles": {
				"runID": "123",
				"uploadHeaders": ["a", "b"],
				"files": [{
					"name": "file1",
					"uploadUrl": "url"
				}]
			}
		}`,
	)

	resp, err := gql.CreateRunFiles(
		context.Background(),
		mock,
		"entity",
		"project",
		"run",
		[]string{},
	)

	url := "url"
	require.NoError(t, err)
	require.Equal(t,
		&gql.CreateRunFilesResponse{
			CreateRunFiles: &gql.CreateRunFilesCreateRunFilesCreateRunFilesPayload{
				RunID:         "123",
				UploadHeaders: []string{"a", "b"},
				Files: []gql.CreateRunFilesCreateRunFilesCreateRunFilesPayloadFilesFile{
					{Name: "file1", UploadUrl: &url},
				},
			},
		},
		resp)
}

func TestStubOnce_WorksOnlyOnce(t *testing.T) {
	testRequest := func(client graphql.Client) error {
		return client.MakeRequest(
			context.Background(),
			&graphql.Request{},
			&graphql.Response{Data: &struct{}{}},
		)
	}

	mock := gqlmock.NewMockClient()
	mock.StubOnce(
		func(client graphql.Client) { _ = testRequest(client) },
		"null",
	)

	assert.False(t, mock.AllStubsUsed())
	assert.NoError(t, testRequest(mock))
	assert.True(t, mock.AllStubsUsed())
	assert.Error(t, testRequest(mock))
}
