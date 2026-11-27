package wbapi_test

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"

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

func consoleLogsRespMap(
	logLineCount any,
	edges []map[string]any,
	hasNextPage bool,
	endCursor string,
) map[string]any {
	return map[string]any{
		"project": map[string]any{
			"run": map[string]any{
				"logLineCount": logLineCount,
				"logLines": map[string]any{
					"edges": edges,
					"pageInfo": map[string]any{
						"endCursor":   endCursor,
						"hasNextPage": hasNextPage,
					},
				},
			},
		},
	}
}

func consoleLogEdge(number int, line string) map[string]any {
	return map[string]any{
		"node": map[string]any{
			"number":    number,
			"timestamp": "2026-01-01T00:00:00Z",
			"level":     "",
			"label":     "",
			"line":      line,
		},
	}
}

func requestVariables(t *testing.T, client *fakeGQLClient) map[string]any {
	t.Helper()
	// The genqlient variables struct is unexported; round-trip through JSON.
	varsJSON, err := json.Marshal(client.gotReq.Variables)
	require.NoError(t, err)
	var vars map[string]any
	require.NoError(t, json.Unmarshal(varsJSON, &vars))
	return vars
}

func TestReadRunConsoleLogsTail(t *testing.T) {
	// The pageInfo values simulate the legacy backwards-offset cursors a
	// tail response carries; the tail query does not select pageInfo, so
	// they must never surface in the response.
	client := &fakeGQLClient{
		respMap: consoleLogsRespMap(1512, []map[string]any{
			consoleLogEdge(1510, "second to last"),
			consoleLogEdge(1511, "last"),
		}, true, "legacy-cursor"),
	}
	handler := wbapi.NewRunHandler(client)

	response := handler.HandleReadRunConsoleLogs(
		context.Background(),
		&spb.ReadRunConsoleLogsRequest{
			Entity:  "test-entity",
			Project: "test-project",
			RunId:   "test-run",
			Last:    proto.Int32(2),
		},
	)

	logs := response.GetReadRunConsoleLogsResponse()
	require.NotNil(t, logs)
	assert.Equal(t, "RunConsoleLogTail", client.gotReq.OpName)

	vars := requestVariables(t, client)
	assert.Equal(t, "test-entity", vars["entity"])
	assert.Equal(t, "test-project", vars["project"])
	assert.Equal(t, "test-run", vars["runName"])
	assert.Equal(t, float64(2), vars["last"])

	require.Len(t, logs.GetLines(), 2)
	assert.Equal(t, int64(1510), logs.GetLines()[0].GetNumber())
	assert.Equal(t, "second to last", logs.GetLines()[0].GetContent())
	assert.Equal(t, "last", logs.GetLines()[1].GetContent())
	// A tail's cursors come from the backend's legacy pagination and must
	// not be offered for forward pagination.
	assert.Empty(t, logs.GetEndCursor())
	assert.False(t, logs.GetHasNextPage())
	assert.Equal(t, int64(1512), logs.GetTotalLines())
}

func TestReadRunConsoleLogsNullProject(t *testing.T) {
	// The backend returns a null project when it does not exist or the
	// credentials cannot read it; this must not crash the handler.
	client := &fakeGQLClient{
		respMap: map[string]any{"project": nil},
	}
	handler := wbapi.NewRunHandler(client)

	for _, request := range []*spb.ReadRunConsoleLogsRequest{
		{Entity: "e", Project: "p", RunId: "r", Last: proto.Int32(10)},
		{Entity: "e", Project: "p", RunId: "r", First: proto.Int32(10)},
	} {
		response := handler.HandleReadRunConsoleLogs(context.Background(), request)

		require.NotNil(t, response.GetApiErrorResponse())
		assert.Contains(t, response.GetApiErrorResponse().GetMessage(), "run e/p/r not found")
	}
}

func TestReadRunConsoleLogsForwardPage(t *testing.T) {
	client := &fakeGQLClient{
		respMap: consoleLogsRespMap(3, []map[string]any{
			consoleLogEdge(0, "l0"),
			consoleLogEdge(1, "l1"),
		}, true, "c1"),
	}
	handler := wbapi.NewRunHandler(client)

	response := handler.HandleReadRunConsoleLogs(
		context.Background(),
		&spb.ReadRunConsoleLogsRequest{
			Entity:  "test-entity",
			Project: "test-project",
			RunId:   "test-run",
			First:   proto.Int32(2),
			After:   proto.String("c-prev"),
		},
	)

	logs := response.GetReadRunConsoleLogsResponse()
	require.NotNil(t, logs)
	assert.Equal(t, "RunConsoleLogPage", client.gotReq.OpName)

	vars := requestVariables(t, client)
	assert.Equal(t, float64(2), vars["first"])
	assert.Equal(t, "c-prev", vars["after"])

	require.Len(t, logs.GetLines(), 2)
	assert.Equal(t, "c1", logs.GetEndCursor())
	assert.True(t, logs.GetHasNextPage())
	assert.Equal(t, int64(3), logs.GetTotalLines())
}

func TestReadRunConsoleLogsHasNextPage(t *testing.T) {
	// has_next_page must stay honest when the backend cuts a page short
	// on a per-request size budget and reports hasNextPage=false mid-log:
	// line numbers are absolute, so a page whose last line is not the
	// log's last line has a next page. A page without a resume cursor is
	// always final, and a null logLineCount falls back to the flag.
	for _, tc := range []struct {
		name        string
		respMap     map[string]any
		wantHasNext bool
	}{
		{
			name: "budget-cut page with lines remaining",
			respMap: consoleLogsRespMap(4, []map[string]any{
				consoleLogEdge(0, "l0"), consoleLogEdge(1, "l1"),
			}, false, "c1"),
			wantHasNext: true,
		},
		{
			name: "final page",
			respMap: consoleLogsRespMap(3, []map[string]any{
				consoleLogEdge(2, "l2"),
			}, false, "c2"),
			wantHasNext: false,
		},
		{
			name: "no cursor to resume from",
			respMap: consoleLogsRespMap(4, []map[string]any{
				consoleLogEdge(0, "l0"),
			}, true, ""),
			wantHasNext: false,
		},
		{
			name: "null logLineCount trusts the backend flag",
			respMap: consoleLogsRespMap(nil, []map[string]any{
				consoleLogEdge(0, "l0"),
			}, false, "c0"),
			wantHasNext: false,
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			handler := wbapi.NewRunHandler(&fakeGQLClient{respMap: tc.respMap})

			response := handler.HandleReadRunConsoleLogs(
				context.Background(),
				&spb.ReadRunConsoleLogsRequest{
					Entity:  "e",
					Project: "p",
					RunId:   "r",
					First:   proto.Int32(1000),
				},
			)

			logs := response.GetReadRunConsoleLogsResponse()
			require.NotNil(t, logs)
			assert.Equal(t, tc.wantHasNext, logs.GetHasNextPage())
		})
	}
}

func TestReadRunConsoleLogsFieldsMapped(t *testing.T) {
	client := &fakeGQLClient{
		respMap: consoleLogsRespMap(1, []map[string]any{{
			"node": map[string]any{
				"number":    7,
				"timestamp": "2026-01-02T03:04:05.678Z",
				"level":     "error",
				"label":     "rank-1",
				"line":      "boom",
			},
		}}, false, "c7"),
	}
	handler := wbapi.NewRunHandler(client)

	response := handler.HandleReadRunConsoleLogs(
		context.Background(),
		&spb.ReadRunConsoleLogsRequest{
			Entity:  "e",
			Project: "p",
			RunId:   "r",
			Last:    proto.Int32(1),
		},
	)

	lines := response.GetReadRunConsoleLogsResponse().GetLines()
	require.Len(t, lines, 1)
	assert.Equal(t, int64(7), lines[0].GetNumber())
	assert.Equal(t, "2026-01-02T03:04:05.678Z", lines[0].GetTimestamp())
	assert.Equal(t, "error", lines[0].GetLevel())
	assert.Equal(t, "rank-1", lines[0].GetLabel())
	assert.Equal(t, "boom", lines[0].GetContent())
}

func TestReadRunConsoleLogsRejectsLastWithForwardArgs(t *testing.T) {
	client := &fakeGQLClient{}
	handler := wbapi.NewRunHandler(client)

	response := handler.HandleReadRunConsoleLogs(
		context.Background(),
		&spb.ReadRunConsoleLogsRequest{
			Entity:  "e",
			Project: "p",
			RunId:   "r",
			First:   proto.Int32(1),
			Last:    proto.Int32(1),
		},
	)

	require.NotNil(t, response.GetApiErrorResponse())
	assert.Contains(t, response.GetApiErrorResponse().GetMessage(), "cannot combine")
	assert.False(t, client.called)
}

func TestReadRunConsoleLogsRejectsNonPositiveLimits(t *testing.T) {
	client := &fakeGQLClient{}
	handler := wbapi.NewRunHandler(client)

	for _, request := range []*spb.ReadRunConsoleLogsRequest{
		{Entity: "e", Project: "p", RunId: "r", Last: proto.Int32(0)},
		{Entity: "e", Project: "p", RunId: "r", First: proto.Int32(-1)},
	} {
		response := handler.HandleReadRunConsoleLogs(context.Background(), request)

		require.NotNil(t, response.GetApiErrorResponse())
		assert.Contains(t, response.GetApiErrorResponse().GetMessage(), "positive")
	}
	assert.False(t, client.called)
}

func TestReadRunConsoleLogsRunNotFound(t *testing.T) {
	client := &fakeGQLClient{
		respMap: map[string]any{"project": map[string]any{"run": nil}},
	}
	handler := wbapi.NewRunHandler(client)

	response := handler.HandleReadRunConsoleLogs(
		context.Background(),
		&spb.ReadRunConsoleLogsRequest{
			Entity:  "e",
			Project: "p",
			RunId:   "r",
			Last:    proto.Int32(10),
		},
	)

	require.NotNil(t, response.GetApiErrorResponse())
	assert.Contains(t, response.GetApiErrorResponse().GetMessage(), "run e/p/r not found")
}

func TestReadRunConsoleLogsNullConnection(t *testing.T) {
	// The backend returns a null logLines connection for a run that never
	// wrote console output.
	client := &fakeGQLClient{
		respMap: map[string]any{
			"project": map[string]any{
				"run": map[string]any{"logLineCount": 0, "logLines": nil},
			},
		},
	}
	handler := wbapi.NewRunHandler(client)

	response := handler.HandleReadRunConsoleLogs(
		context.Background(),
		&spb.ReadRunConsoleLogsRequest{Entity: "e", Project: "p", RunId: "r"},
	)

	logs := response.GetReadRunConsoleLogsResponse()
	require.NotNil(t, logs)
	assert.Empty(t, logs.GetLines())
	assert.False(t, logs.GetHasNextPage())
	assert.Equal(t, int64(0), logs.GetTotalLines())
}

func TestReadRunConsoleLogsOldServerMessage(t *testing.T) {
	client := &fakeGQLClient{
		err: errors.New(`Unknown argument "useImprovedPagination" on field "logLines"`),
	}
	handler := wbapi.NewRunHandler(client)

	response := handler.HandleReadRunConsoleLogs(
		context.Background(),
		&spb.ReadRunConsoleLogsRequest{
			Entity:  "e",
			Project: "p",
			RunId:   "r",
			First:   proto.Int32(1000),
		},
	)

	apiError := response.GetApiErrorResponse()
	require.NotNil(t, apiError)
	assert.Contains(t, apiError.GetMessage(), "W&B server 0.77 or newer")
	assert.Contains(t, apiError.GetMessage(), "useImprovedPagination")
}

func TestReadRunConsoleLogsTailReturnsError(t *testing.T) {
	client := &fakeGQLClient{err: errors.New("boom")}
	handler := wbapi.NewRunHandler(client)

	response := handler.HandleReadRunConsoleLogs(
		context.Background(),
		&spb.ReadRunConsoleLogsRequest{
			Entity:  "e",
			Project: "p",
			RunId:   "r",
			Last:    proto.Int32(10),
		},
	)

	apiError := response.GetApiErrorResponse()
	require.NotNil(t, apiError)
	assert.Contains(t, apiError.GetMessage(), "boom")
}
