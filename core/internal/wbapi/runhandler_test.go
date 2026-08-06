package wbapi_test

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/wbapi"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestStopRunRunsMutation(t *testing.T) {
	client := &fakeGQLClient{
		respMap: map[string]any{"stopRun": map[string]any{"success": true}},
	}
	handler := wbapi.NewRunHandler(client)

	response := handler.HandleStopRun(
		context.Background(),
		&spb.StopRunRequest{StorageId: "run-node-id"},
	)

	require.NotNil(t, response.GetStopRunResponse())
	require.True(t, client.called)
	assert.Equal(t, "StopRun", client.gotReq.OpName)

	// The genqlient variables struct is unexported; round-trip through JSON.
	varsJSON, err := json.Marshal(client.gotReq.Variables)
	require.NoError(t, err)
	var vars map[string]any
	require.NoError(t, json.Unmarshal(varsJSON, &vars))
	assert.Equal(t, "run-node-id", vars["id"])
}

func TestStopRunReturnsError(t *testing.T) {
	client := &fakeGQLClient{err: errors.New("boom")}
	handler := wbapi.NewRunHandler(client)

	response := handler.HandleStopRun(
		context.Background(),
		&spb.StopRunRequest{StorageId: "run-node-id"},
	)

	apiError := response.GetApiErrorResponse()
	require.NotNil(t, apiError)
	assert.Contains(t, apiError.GetMessage(), "boom")
	assert.Equal(t, int32(0), apiError.GetHttpStatus()) // non-HTTP error
}
