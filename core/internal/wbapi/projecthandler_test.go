package wbapi_test

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/wbapi"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestGetProjectInternalIDRunsQuery(t *testing.T) {
	client := &fakeGQLClient{
		respMap: map[string]any{
			"project": map[string]any{"internalId": "opaque-project-id"},
		},
	}
	handler := wbapi.NewProjectHandler(client)

	response := handler.HandleGetProjectInternalID(
		context.Background(),
		&spb.GetProjectInternalIdRequest{
			Entity:  "entity",
			Project: "project",
		},
	)

	projectResponse := response.GetGetProjectInternalIdResponse()
	require.NotNil(t, projectResponse)
	assert.Equal(t, "opaque-project-id", projectResponse.GetProjectInternalId())
	require.True(t, client.called)
	assert.Equal(t, "ProjectInternalID", client.gotReq.OpName)

	var variables map[string]any
	variablesJSON, err := json.Marshal(client.gotReq.Variables)
	require.NoError(t, err)
	require.NoError(t, json.Unmarshal(variablesJSON, &variables))
	assert.Equal(t, "entity", variables["entity"])
	assert.Equal(t, "project", variables["project"])
}

func TestGetProjectInternalIDReturnsQueryError(t *testing.T) {
	handler := wbapi.NewProjectHandler(&fakeGQLClient{err: assert.AnError})

	response := handler.HandleGetProjectInternalID(
		context.Background(),
		&spb.GetProjectInternalIdRequest{},
	)

	apiError := response.GetApiErrorResponse()
	require.NotNil(t, apiError)
	assert.Contains(t, apiError.GetMessage(), assert.AnError.Error())
}

func TestGetProjectInternalIDProjectNotFound(t *testing.T) {
	handler := wbapi.NewProjectHandler(&fakeGQLClient{})

	response := handler.HandleGetProjectInternalID(
		context.Background(),
		&spb.GetProjectInternalIdRequest{
			Entity:  "entity",
			Project: "project",
		},
	)

	projectResponse := response.GetGetProjectInternalIdResponse()
	require.NotNil(t, projectResponse)
	assert.Nil(t, projectResponse.ProjectInternalId)
}
