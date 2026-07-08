package wbapi_test

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/wbapi"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// fakeGQLClient records the request it receives and returns a canned result or
// error.
type fakeGQLClient struct {
	err     error
	called  bool
	gotReq  *graphql.Request
	respMap map[string]any
}

func (c *fakeGQLClient) MakeRequest(
	_ context.Context,
	req *graphql.Request,
	resp *graphql.Response,
) error {
	c.called = true
	c.gotReq = req
	if c.err != nil {
		return c.err
	}
	if c.respMap != nil {
		raw, _ := json.Marshal(c.respMap)
		_ = json.Unmarshal(raw, resp.Data)
	}
	return nil
}

func TestMarkRunFilesUploadedRunsMutation(t *testing.T) {
	client := &fakeGQLClient{
		respMap: map[string]any{"markRunFilesUploaded": map[string]any{"success": true}},
	}
	handler := wbapi.NewRunFilesHandler(client)

	response := handler.HandleMarkRunFilesUploaded(
		context.Background(),
		&spb.MarkRunFilesUploadedRequest{
			Entity:  "test-entity",
			Project: "test-project",
			RunId:   "test-run",
			Files:   []string{"a.txt", "b.txt"},
		},
	)

	require.NotNil(t, response.GetMarkRunFilesUploadedResponse())
	require.True(t, client.called)
	assert.Equal(t, "MarkRunFilesUploaded", client.gotReq.OpName)

	// The genqlient variables struct is unexported; round-trip through JSON.
	varsJSON, err := json.Marshal(client.gotReq.Variables)
	require.NoError(t, err)
	var vars map[string]any
	require.NoError(t, json.Unmarshal(varsJSON, &vars))
	assert.Equal(t, "test-entity", vars["entity"])
	assert.Equal(t, "test-project", vars["project"])
	assert.Equal(t, "test-run", vars["run"])
	assert.Equal(t, []any{"a.txt", "b.txt"}, vars["files"])
}

func TestMarkRunFilesUploadedNoFilesSkipsRequest(t *testing.T) {
	client := &fakeGQLClient{}
	handler := wbapi.NewRunFilesHandler(client)

	response := handler.HandleMarkRunFilesUploaded(
		context.Background(),
		&spb.MarkRunFilesUploadedRequest{
			Entity:  "test-entity",
			Project: "test-project",
			RunId:   "test-run",
		},
	)

	require.NotNil(t, response.GetMarkRunFilesUploadedResponse())
	assert.False(t, client.called)
}

func TestMarkRunFilesUploadedReturnsError(t *testing.T) {
	client := &fakeGQLClient{err: errors.New("boom")}
	handler := wbapi.NewRunFilesHandler(client)

	response := handler.HandleMarkRunFilesUploaded(
		context.Background(),
		&spb.MarkRunFilesUploadedRequest{
			Entity:  "test-entity",
			Project: "test-project",
			RunId:   "test-run",
			Files:   []string{"a.txt"},
		},
	)

	apiError := response.GetApiErrorResponse()
	require.NotNil(t, apiError)
	assert.Contains(t, apiError.GetMessage(), "boom")
	assert.Equal(t, int32(0), apiError.GetHttpStatus()) // non-HTTP error
}
