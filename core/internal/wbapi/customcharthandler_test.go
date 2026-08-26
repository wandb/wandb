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

func TestCreateCustomChartRunsMutation(t *testing.T) {
	client := &fakeGQLClient{
		respMap: map[string]any{
			"createCustomChart": map[string]any{
				"chart": map[string]any{"id": "entity/chart"},
			},
		},
	}
	handler := wbapi.NewCustomChartHandler(client)

	response := handler.HandleCreateCustomChart(
		context.Background(),
		&spb.CreateCustomChartRequest{
			Entity:      "entity",
			Name:        "chart",
			DisplayName: "Chart",
			SpecType:    "vega2",
			Access:      "PRIVATE",
			Spec:        `{"mark":"bar"}`,
		},
	)

	require.NotNil(t, response.GetCreateCustomChartResponse())
	assert.Equal(
		t,
		"entity/chart",
		response.GetCreateCustomChartResponse().GetChartId(),
	)
	require.True(t, client.called)
	assert.Equal(t, "CreateCustomChart", client.gotReq.OpName)

	// The genqlient variables struct is unexported; Check through JSON.
	varsJSON, err := json.Marshal(client.gotReq.Variables)
	require.NoError(t, err)
	var vars map[string]any
	require.NoError(t, json.Unmarshal(varsJSON, &vars))
	assert.Equal(t, "entity", vars["entity"])
	assert.Equal(t, "chart", vars["chartName"])
	assert.Equal(t, "Chart", vars["displayName"])
	assert.Equal(t, "vega2", vars["chartType"])
	assert.Equal(t, "PRIVATE", vars["access"])
	assert.Equal(t, `{"mark":"bar"}`, vars["spec"])
}

func TestCreateCustomChartReturnsError(t *testing.T) {
	handler := wbapi.NewCustomChartHandler(
		&fakeGQLClient{err: assert.AnError},
	)

	response := handler.HandleCreateCustomChart(
		context.Background(),
		&spb.CreateCustomChartRequest{},
	)

	apiError := response.GetApiErrorResponse()
	require.NotNil(t, apiError)
	assert.Contains(t, apiError.GetMessage(), assert.AnError.Error())
	assert.Equal(t, int32(0), apiError.GetHttpStatus()) // non-HTTP error
}

func TestCreateCustomChartReturnsErrorWhenPayloadIsMissing(t *testing.T) {
	handler := wbapi.NewCustomChartHandler(&fakeGQLClient{})

	response := handler.HandleCreateCustomChart(
		context.Background(),
		&spb.CreateCustomChartRequest{},
	)

	apiError := response.GetApiErrorResponse()
	require.NotNil(t, apiError)
	assert.Equal(t, "failed to create custom chart", apiError.GetMessage())
}
