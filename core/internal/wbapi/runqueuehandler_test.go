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

func TestCreateDefaultResourceConfigRunsMutation(t *testing.T) {
	templateVariables := `{"image":{"type":"string"}}`
	client := &fakeGQLClient{
		respMap: map[string]any{
			"createDefaultResourceConfig": map[string]any{
				"defaultResourceConfigID": "config-id",
				"success":                 true,
			},
		},
	}
	handler := wbapi.NewRunQueueHandler(client)

	response := handler.HandleRequest(
		context.Background(),
		&spb.RunQueueOperationRequest{
			Operation: &spb.RunQueueOperationRequest_CreateDefaultResourceConfigRequest{
				CreateDefaultResourceConfigRequest: &spb.CreateDefaultResourceConfigRequest{
					EntityName:        "test-entity",
					Resource:          "kubernetes",
					Config:            `{"resource_args":{}}`,
					TemplateVariables: &templateVariables,
				},
			},
		},
	)

	runQueueResponse := response.GetRunQueueOperationResponse()
	require.NotNil(t, runQueueResponse)
	result := runQueueResponse.GetCreateDefaultResourceConfigResponse()
	require.NotNil(t, result)
	assert.True(t, result.GetSuccess())
	assert.Equal(t, "config-id", result.GetDefaultResourceConfigId())
	assert.Equal(t, "CreateDefaultResourceConfig", client.gotReq.OpName)
	assertVariables(t, client, map[string]any{
		"entityName":        "test-entity",
		"resource":          "kubernetes",
		"config":            `{"resource_args":{}}`,
		"templateVariables": templateVariables,
	})
}

func TestCreateDefaultResourceConfigReturnsError(t *testing.T) {
	response := wbapi.NewRunQueueHandler(&fakeGQLClient{err: assert.AnError}).
		HandleRequest(
			context.Background(),
			&spb.RunQueueOperationRequest{
				Operation: &spb.RunQueueOperationRequest_CreateDefaultResourceConfigRequest{
					CreateDefaultResourceConfigRequest: &spb.CreateDefaultResourceConfigRequest{},
				},
			},
		)

	require.NotNil(t, response.GetApiErrorResponse())
	assert.Contains(t, response.GetApiErrorResponse().GetMessage(), assert.AnError.Error())
}

func TestCreateRunQueueRunsMutation(t *testing.T) {
	prioritizationMode := "V0"
	configID := "config-id"
	client := &fakeGQLClient{
		respMap: map[string]any{
			"createRunQueue": map[string]any{
				"success": true,
				"queueID": "queue-id",
			},
		},
	}
	handler := wbapi.NewRunQueueHandler(client)

	response := handler.HandleRequest(
		context.Background(),
		&spb.RunQueueOperationRequest{
			Operation: &spb.RunQueueOperationRequest_CreateRunQueueRequest{
				CreateRunQueueRequest: &spb.CreateRunQueueRequest{
					Entity:                  "test-entity",
					Project:                 "launch",
					QueueName:               "queue",
					Access:                  "PROJECT",
					PrioritizationMode:      &prioritizationMode,
					DefaultResourceConfigId: &configID,
				},
			},
		},
	)

	runQueueResponse := response.GetRunQueueOperationResponse()
	require.NotNil(t, runQueueResponse)
	result := runQueueResponse.GetCreateRunQueueResponse()
	require.NotNil(t, result)
	assert.True(t, result.GetSuccess())
	assert.Equal(t, "queue-id", result.GetQueueId())
	assert.Equal(t, "CreateRunQueue", client.gotReq.OpName)
	assertVariables(t, client, map[string]any{
		"entity":                  "test-entity",
		"project":                 "launch",
		"queueName":               "queue",
		"access":                  "PROJECT",
		"prioritizationMode":      prioritizationMode,
		"defaultResourceConfigID": configID,
	})
}

func TestCreateRunQueueReturnsError(t *testing.T) {
	response := wbapi.NewRunQueueHandler(&fakeGQLClient{err: assert.AnError}).
		HandleRequest(
			context.Background(),
			&spb.RunQueueOperationRequest{
				Operation: &spb.RunQueueOperationRequest_CreateRunQueueRequest{
					CreateRunQueueRequest: &spb.CreateRunQueueRequest{},
				},
			},
		)

	require.NotNil(t, response.GetApiErrorResponse())
	assert.Contains(t, response.GetApiErrorResponse().GetMessage(), assert.AnError.Error())
}

func TestUpsertRunQueueRunsMutation(t *testing.T) {
	templateVariables := `{"image":{"type":"string"}}`
	prioritizationMode := "V0"
	externalLinks := `{"links":[{"label":"docs","url":"https://example.test"}]}`
	clientMutationID := "client-id"
	client := &fakeGQLClient{
		respMap: map[string]any{
			"upsertRunQueue": map[string]any{
				"success":                      true,
				"configSchemaValidationErrors": []string{"invalid image"},
			},
		},
	}
	handler := wbapi.NewRunQueueHandler(client)

	response := handler.HandleRequest(
		context.Background(),
		&spb.RunQueueOperationRequest{
			Operation: &spb.RunQueueOperationRequest_UpsertRunQueueRequest{
				UpsertRunQueueRequest: &spb.UpsertRunQueueRequest{
					EntityName:         "test-entity",
					ProjectName:        "launch",
					QueueName:          "queue",
					ResourceType:       "kubernetes",
					ResourceConfig:     `{"resource_args":{}}`,
					TemplateVariables:  &templateVariables,
					PrioritizationMode: &prioritizationMode,
					ExternalLinks:      &externalLinks,
					ClientMutationId:   &clientMutationID,
				},
			},
		},
	)

	runQueueResponse := response.GetRunQueueOperationResponse()
	require.NotNil(t, runQueueResponse)
	result := runQueueResponse.GetUpsertRunQueueResponse()
	require.NotNil(t, result)
	assert.True(t, result.GetSuccess())
	assert.Equal(t, []string{"invalid image"}, result.GetConfigSchemaValidationErrors())
	assert.Equal(t, "UpsertRunQueue", client.gotReq.OpName)
	assertVariables(t, client, map[string]any{
		"entityName":         "test-entity",
		"projectName":        "launch",
		"queueName":          "queue",
		"resourceType":       "kubernetes",
		"resourceConfig":     `{"resource_args":{}}`,
		"templateVariables":  templateVariables,
		"prioritizationMode": prioritizationMode,
		"externalLinks":      externalLinks,
		"clientMutationId":   clientMutationID,
	})
}

func TestUpsertRunQueueReturnsError(t *testing.T) {
	response := wbapi.NewRunQueueHandler(&fakeGQLClient{err: assert.AnError}).
		HandleRequest(
			context.Background(),
			&spb.RunQueueOperationRequest{
				Operation: &spb.RunQueueOperationRequest_UpsertRunQueueRequest{
					UpsertRunQueueRequest: &spb.UpsertRunQueueRequest{},
				},
			},
		)

	require.NotNil(t, response.GetApiErrorResponse())
	assert.Contains(t, response.GetApiErrorResponse().GetMessage(), assert.AnError.Error())
}

func assertVariables(t *testing.T, client *fakeGQLClient, want map[string]any) {
	t.Helper()
	require.True(t, client.called)

	varsJSON, err := json.Marshal(client.gotReq.Variables)
	require.NoError(t, err)
	var got map[string]any
	require.NoError(t, json.Unmarshal(varsJSON, &got))
	assert.Equal(t, want, got)
}
