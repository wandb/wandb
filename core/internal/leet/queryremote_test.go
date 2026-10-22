package leet_test

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"strconv"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"

	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/leet"
)

// leetRun is the LeetRun fragment of the run abc as the W&B server returns it.
const leetRun = `"name":"abc","displayName":"first","state":"finished","notes":"n",` +
	`"tags":["t"],"config":"{\"lr\":{\"value\":0.1}}",` +
	`"createdAt":"2026-10-21T00:00:00Z","heartbeatAt":"2026-10-21T00:05:00Z"`

const runInfo = `{"project":{"run":{` + leetRun + `,"systemMetrics":"",` +
	`"summaryMetrics":"{\"_step\":70,\"acc\":0.9,\"loss\":0.1,\"_wandb.runtime\":5}"}}}`

// logLine is a console line as the W&B server returns it: stamped in UTC
// without a zone, and leveled info or error.
func logLine(number int, level, line string) string {
	return `{"node":{"number":` + strconv.Itoa(number) +
		`,"timestamp":"2026-10-21T00:04:00.5","level":"` + level +
		`","label":"w0","line":"` + line + `"}}`
}

func remoteQuery(t *testing.T, out *bytes.Buffer, err error) map[string]any {
	t.Helper()
	require.NoError(t, err)
	var obj map[string]any
	require.NoError(t, json.Unmarshal(out.Bytes(), &obj), out.String())
	return obj
}

func TestListRemoteRuns_PagesAndDedupes(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(gqlmock.WithOpName("QueryProjectRuns"),
		`{"project":{"runs":{"edges":[{"node":{`+leetRun+`}}],`+
			`"pageInfo":{"endCursor":"c1","hasNextPage":true}}}}`)
	client.StubMatchOnce(
		gomock.All(gqlmock.WithOpName("QueryProjectRuns"),
			gqlmock.WithVariables(gqlmock.GQLVar("cursor", gomock.Eq("c1")))),
		`{"project":{"runs":{"edges":[{"node":{`+leetRun+`}},`+
			`{"node":{"name":"def","state":"running","createdAt":"2026-10-20T00:00:00Z"}}],`+
			`"pageInfo":{"endCursor":null,"hasNextPage":false}}}}`)
	params := &leet.RemoteRunParams{BaseURL: "https://api.wandb.ai", Entity: "e", Project: "p"}

	var out bytes.Buffer
	err := leet.ListRemoteRunsWith(leet.NewRemoteClientsForTest(client), params,
		leet.RunsQuery{}, &out)
	obj := remoteQuery(t, &out, err)

	assert.True(t, client.AllStubsUsed())
	assert.Equal(t, "leet.runs/1", obj["schema"])
	assert.Equal(t, map[string]any{
		"kind": "remote", "path": nil, "url": "https://api.wandb.ai/e/p",
		"entity": "e", "project": "p", "run_id": nil,
	}, obj["source"])
	assert.EqualValues(t, 2, obj["total"])
	assert.Equal(t, false, obj["truncated"])
	runs := obj["runs"].([]any)
	require.Len(t, runs, 2)
	assert.Equal(t, map[string]any{
		"run_key": nil, "run_id": "abc", "name": "first", "entity": "e", "project": "p",
		"state": "finished", "state_detail": "finished",
		"start_time": "2026-10-21T00:00:00Z", "last_write": "2026-10-21T00:05:00Z",
		"exit_code": nil, "step": nil, "tags": []any{"t"}, "notes": "n", "file": nil,
		"selected": false, "pinned": false,
	}, runs[0])
	second := runs[1].(map[string]any)
	assert.Equal(t, "def", second["name"])
	assert.Equal(t, "running", second["state"])
	assert.Nil(t, second["last_write"])
}

func TestQueryRemoteSummary(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(gqlmock.WithOpName("QueryRunInfo"), runInfo)
	client.StubMatchOnce(gqlmock.WithOpName("RunConsoleLogTail"),
		`{"project":{"run":{"logLineCount":3,"logLines":{"edges":[`+
			logLine(2, "error", `\u001b[31mboom\u001b[0m`)+`]}}}}`)
	params := &leet.RemoteRunParams{
		BaseURL: "https://api.wandb.ai", Entity: "e", Project: "p", RunID: "abc",
	}

	var out bytes.Buffer
	err := leet.QueryRemoteSummaryWith(leet.NewRemoteClientsForTest(client), params,
		leet.SummaryQuery{Keys: []string{"acc", "nope"}}, &out)
	obj := remoteQuery(t, &out, err)

	assert.True(t, client.AllStubsUsed())
	assert.Equal(t, "leet.summary/1", obj["schema"])
	assert.Equal(t, "https://api.wandb.ai/e/p/runs/abc", obj["source"].(map[string]any)["url"])
	assert.Equal(t, "first", obj["name"])
	assert.Equal(t, "finished", obj["state"])
	assert.EqualValues(t, 70, obj["step"])
	assert.Equal(t, map[string]any{"lr": 0.1}, obj["config"])
	assert.Equal(t, map[string]any{"acc": 0.9}, obj["summary"])
	assert.Nil(t, obj["history_keys"])
	assert.Nil(t, obj["exit_code"])
	assert.Equal(t, "2026-10-21T00:05:00Z", obj["last_write"])
	assert.Equal(t, []any{map[string]any{
		"number": 2.0, "timestamp": "2026-10-21T00:04:00Z", "level": "error",
		"label": "w0", "content": "boom",
	}}, obj["console"])
	assert.EqualValues(t, 3, obj["console_lines"])
	assert.Equal(t, []any{
		"history keys are not available for remote runs", `no key matches "nope"`,
	}, obj["warnings"])
}

func TestQueryRemoteConsole_PageCursorAndTail(t *testing.T) {
	client := gqlmock.NewMockClient()
	params := &leet.RemoteRunParams{
		BaseURL: "https://api.wandb.ai", Entity: "e", Project: "p", RunID: "abc",
	}
	query := func(q leet.ConsoleQuery) map[string]any {
		var out bytes.Buffer
		err := leet.QueryRemoteConsoleWith(leet.NewRemoteClientsForTest(client), params, q, &out)
		return remoteQuery(t, &out, err)
	}

	local := base64.RawURLEncoding.EncodeToString([]byte(`{"v":1,"n":5,"f":"abc"}`))
	err := leet.QueryRemoteConsoleWith(leet.NewRemoteClientsForTest(client), params,
		leet.ConsoleQuery{After: local}, &bytes.Buffer{})
	var qerr *leet.QueryError
	require.ErrorAs(t, err, &qerr)
	assert.Equal(t, "bad_request", qerr.Code)

	client.StubMatchOnce(gqlmock.WithOpName("QueryRunInfo"), runInfo)
	client.StubMatchOnce(gqlmock.WithOpName("RunConsoleLogPage"),
		`{"project":{"run":{"logLineCount":3,"logLines":{"edges":[`+
			logLine(0, "info", "a")+`,`+logLine(1, "error", "b")+`],`+
			`"pageInfo":{"endCursor":"k1","hasNextPage":true}}}}}`)
	page := query(leet.ConsoleQuery{Limit: 2})
	assert.Equal(t, "finished", page["state"])
	assert.EqualValues(t, 3, page["total_lines"])
	assert.EqualValues(t, 2, page["matched_lines"])
	assert.Equal(t, true, page["truncated"])
	assert.Equal(t, true, page["has_more"])
	cursor, _ := page["next_cursor"].(string)
	raw, err := base64.RawURLEncoding.DecodeString(cursor)
	require.NoError(t, err)
	assert.JSONEq(t, `{"v":1,"c":"k1","f":"abc"}`, string(raw))

	client.StubMatchOnce(gqlmock.WithOpName("QueryRunInfo"), runInfo)
	client.StubMatchOnce(
		gomock.All(gqlmock.WithOpName("RunConsoleLogPage"),
			gqlmock.WithVariables(gqlmock.GQLVar("after", gomock.Eq("k1")))),
		`{"project":{"run":{"logLineCount":3,"logLines":{"edges":[`+logLine(2, "info", "c")+`],`+
			`"pageInfo":{"endCursor":"k2","hasNextPage":false}}}}}`)
	page = query(leet.ConsoleQuery{Limit: 2, After: cursor})
	assert.Equal(t, []any{map[string]any{
		"number": 2.0, "timestamp": "2026-10-21T00:04:00Z", "level": "", "label": "w0",
		"content": "c",
	}}, page["lines"])
	assert.Equal(t, false, page["has_more"])
	assert.Nil(t, page["next_cursor"])

	client.StubMatchOnce(gqlmock.WithOpName("QueryRunInfo"),
		strings.Replace(runInfo, `"state":"finished"`, `"state":"running"`, 1))
	client.StubMatchOnce(
		gomock.All(gqlmock.WithOpName("RunConsoleLogPage"),
			gqlmock.WithVariables(gqlmock.GQLVar("after", gomock.Eq("k1")))),
		`{"project":{"run":{"logLineCount":2,"logLines":{"edges":[],`+
			`"pageInfo":{"endCursor":null,"hasNextPage":false}}}}}`)
	quiet := query(leet.ConsoleQuery{Limit: 2, After: cursor})
	assert.Equal(t, "running", quiet["state"])
	assert.Empty(t, quiet["lines"])
	assert.Equal(t, cursor, quiet["next_cursor"])

	client.StubMatchOnce(gqlmock.WithOpName("QueryRunInfo"), runInfo)
	client.StubMatchOnce(gqlmock.WithOpName("RunConsoleLogTail"),
		`{"project":{"run":{"logLineCount":3,"logLines":{"edges":[`+
			logLine(1, "info", "b")+`,`+logLine(2, "info", "boom")+`]}}}}`)
	tail := query(leet.ConsoleQuery{Last: 2, Grep: "boo"})
	assert.True(t, client.AllStubsUsed())
	assert.Len(t, tail["lines"], 1)
	assert.EqualValues(t, 1, tail["matched_lines"])
	assert.Equal(t, true, tail["truncated"])
	assert.Equal(t, false, tail["has_more"])
	assert.Nil(t, tail["next_cursor"])
	assert.Equal(t, []any{"grep and since filtered only the last 2 lines the server" +
		" returned; page with limit to search the whole log"}, tail["warnings"])
}
