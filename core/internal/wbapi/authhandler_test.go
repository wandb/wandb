package wbapi_test

import (
	"context"
	"errors"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/wbapi"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestAuthenticateReturnsViewerInfo(t *testing.T) {
	client := &fakeGQLClient{
		respMap: map[string]any{
			"viewer": map[string]any{
				"id":       "user-node-id",
				"entity":   "myentity",
				"username": "myuser",
				"email":    "me@example.com",
				"flags":    `{"code_saving_enabled": true}`,
				"teams": map[string]any{
					"edges": []any{
						map[string]any{"node": map[string]any{"name": "team1"}},
						map[string]any{"node": map[string]any{"name": "team2"}},
					},
				},
			},
		},
	}
	handler := wbapi.NewAuthHandler(client)

	response := handler.HandleAuthenticate(
		context.Background(),
		&spb.AuthenticateRequest{},
	)

	authResponse := response.GetAuthenticateResponse()
	require.NotNil(t, authResponse)
	require.True(t, client.called)
	assert.Equal(t, "Viewer", client.gotReq.OpName)
	assert.Equal(t, "myentity", authResponse.GetDefaultEntity())
	assert.Equal(t, "myuser", authResponse.GetUsername())
	assert.Equal(t, "me@example.com", authResponse.GetEmail())
	assert.Equal(t, `{"code_saving_enabled": true}`, authResponse.GetFlagsJson())
	assert.Equal(t, []string{"team1", "team2"}, authResponse.GetTeams())
}

func TestAuthenticateNullEntityIsAccepted(t *testing.T) {
	// Unusual accounts and old server versions may return a viewer with
	// null fields; the credentials are still valid.
	client := &fakeGQLClient{
		respMap: map[string]any{
			"viewer": map[string]any{
				"id":       "user-node-id",
				"username": "myuser",
			},
		},
	}
	handler := wbapi.NewAuthHandler(client)

	response := handler.HandleAuthenticate(
		context.Background(),
		&spb.AuthenticateRequest{},
	)

	authResponse := response.GetAuthenticateResponse()
	require.NotNil(t, authResponse)
	assert.Equal(t, "", authResponse.GetDefaultEntity())
	assert.Equal(t, "myuser", authResponse.GetUsername())
}

func TestAuthenticatePartialDataIsAccepted(t *testing.T) {
	// Field-level GraphQL errors don't invalidate the credentials when the
	// viewer itself resolved; genqlient returns partial data plus an error.
	client := &fakeGQLClient{
		err: errors.New("resolver for field 'teams' failed"),
		respMap: map[string]any{
			"viewer": map[string]any{
				"id":     "user-node-id",
				"entity": "myentity",
			},
		},
	}
	handler := wbapi.NewAuthHandler(client)

	response := handler.HandleAuthenticate(
		context.Background(),
		&spb.AuthenticateRequest{},
	)

	authResponse := response.GetAuthenticateResponse()
	require.NotNil(t, authResponse)
	assert.Equal(t, "myentity", authResponse.GetDefaultEntity())
}

func TestAuthenticateNullViewerIsError(t *testing.T) {
	client := &fakeGQLClient{
		respMap: map[string]any{"viewer": nil},
	}
	handler := wbapi.NewAuthHandler(client)

	response := handler.HandleAuthenticate(
		context.Background(),
		&spb.AuthenticateRequest{},
	)

	apiError := response.GetApiErrorResponse()
	require.NotNil(t, apiError)
	assert.Contains(t, apiError.GetMessage(), "invalid credentials")
}

func TestAuthenticateReturnsError(t *testing.T) {
	client := &fakeGQLClient{err: errors.New("boom")}
	handler := wbapi.NewAuthHandler(client)

	response := handler.HandleAuthenticate(
		context.Background(),
		&spb.AuthenticateRequest{},
	)

	apiError := response.GetApiErrorResponse()
	require.NotNil(t, apiError)
	assert.Contains(t, apiError.GetMessage(), "boom")
	assert.Equal(t, int32(0), apiError.GetHttpStatus()) // non-HTTP error
}
