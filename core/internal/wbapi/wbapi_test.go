package wbapi

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/Khan/genqlient/graphql"
	"google.golang.org/protobuf/proto"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// stubGQLClient returns a canned GraphQL result for any request.
type stubGQLClient struct {
	respJSON string
}

func (c stubGQLClient) MakeRequest(
	_ context.Context,
	_ *graphql.Request,
	resp *graphql.Response,
) error {
	return json.Unmarshal([]byte(c.respJSON), resp.Data)
}

func TestHandleRequestRoutesReadRunConsoleLogs(t *testing.T) {
	api := &WandbAPI{
		semaphore: make(chan struct{}, 1),
		runHandler: NewRunHandler(stubGQLClient{
			respJSON: `{"project": {"run": {"logLineCount": 1, "logLines": {
				"edges": [{"node": {"number": 0, "timestamp": "t", "level": "info",
				"label": "", "line": "hello"}, "cursor": "c0"}]}}}}`,
		}),
	}

	response := api.HandleRequest(
		context.Background(),
		"request-id",
		&spb.ApiRequest{
			Request: &spb.ApiRequest_ReadRunConsoleLogsRequest{
				ReadRunConsoleLogsRequest: &spb.ReadRunConsoleLogsRequest{
					Entity:  "e",
					Project: "p",
					RunId:   "r",
					Last:    proto.Int32(1),
				},
			},
		},
	)

	logs := response.GetReadRunConsoleLogsResponse()
	if logs == nil {
		t.Fatalf("expected ReadRunConsoleLogsResponse, got %v", response)
	}
	if len(logs.GetLines()) != 1 || logs.GetLines()[0].GetContent() != "hello" {
		t.Fatalf("unexpected lines: %v", logs.GetLines())
	}
}

func TestHandleRequestUnknownTypeIsError(t *testing.T) {
	// A newer client attached to an older wandb-core sends request types
	// this version doesn't know; they must get an error response instead
	// of no response (which would make the client wait until its timeout).
	api := &WandbAPI{
		semaphore: make(chan struct{}, 1),
	}

	response := api.HandleRequest(
		context.Background(),
		"request-id",
		&spb.ApiRequest{},
	)

	apiError := response.GetApiErrorResponse()
	if apiError == nil {
		t.Fatal("expected API error response")
	}
	if !strings.Contains(apiError.GetMessage(), "unsupported API request") {
		t.Fatalf("expected unsupported request error, got %q", apiError.GetMessage())
	}
}

func TestHandleRequestReturnsWhenCancelledWaitingForConcurrency(t *testing.T) {
	api := &WandbAPI{
		semaphore: make(chan struct{}, 1),
	}
	api.semaphore <- struct{}{}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan *spb.ApiResponse, 1)
	go func() {
		done <- api.HandleRequest(ctx, "request-id", &spb.ApiRequest{})
	}()

	cancel()

	select {
	case response := <-done:
		apiError := response.GetApiErrorResponse()
		if apiError == nil {
			t.Fatal("expected API error response")
		}
		if !strings.Contains(apiError.GetMessage(), "context canceled") {
			t.Fatalf("expected context cancellation error, got %q", apiError.GetMessage())
		}
	case <-time.After(time.Second):
		t.Fatal("HandleRequest did not return after context cancellation")
	}
}
