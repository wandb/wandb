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
	`"summaryMetrics":"{\"_step\":70,\"_runtime\":9.5,\"acc\":0.9,\"loss\":0.1,` +
	`\"_wandb.runtime\":5}"}}}`

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

// histRow is a live history row as the W&B server returns it.
func histRow(step int, rest string) string {
	return `"{\"_step\":` + strconv.Itoa(step) + `,` + rest + `}"`
}

func TestQueryRemoteHistory_RowsPageAndCursor(t *testing.T) {
	t.Setenv("WANDB_CACHE_DIR", t.TempDir())
	client := gqlmock.NewMockClient()
	params := &leet.RemoteRunParams{
		BaseURL: "https://api.wandb.ai", Entity: "e", Project: "p", RunID: "abc",
	}
	const noParquet = `{"project":{"run":{"parquetHistory":{"parquetUrls":[],"liveData":[]}}}}`
	query := func(q leet.HistoryQuery) map[string]any {
		var out bytes.Buffer
		err := leet.QueryRemoteHistoryWith(leet.NewRemoteClientsForTest(client), params, q, &out)
		return remoteQuery(t, &out, err)
	}

	local := base64.RawURLEncoding.EncodeToString([]byte(`{"v":1,"o":5,"f":"abc"}`))
	err := leet.QueryRemoteHistoryWith(leet.NewRemoteClientsForTest(client), params,
		leet.HistoryQuery{Keys: []string{"loss"}, After: local}, &bytes.Buffer{})
	var qerr *leet.QueryError
	require.ErrorAs(t, err, &qerr)
	assert.Equal(t, "bad_request", qerr.Code)

	client.StubMatchOnce(gqlmock.WithOpName("QueryRunInfo"), runInfo)
	client.StubMatchOnce(gqlmock.WithOpName("RunParquetHistory"), noParquet)
	client.StubMatchOnce(
		gomock.All(gqlmock.WithOpName("HistoryPage"),
			gqlmock.WithVariables(gqlmock.GQLVar("minStep", gomock.Eq(0.0)),
				gqlmock.GQLVar("maxStep", gomock.Eq(71.0)))),
		`{"project":{"run":{"history":[`+
			histRow(0, `\"loss\":1.5,\"_runtime\":1,\"note\":\"x\"`)+`,`+
			histRow(1, `\"loss\":1.25,\"_runtime\":2,\"acc\":0.5`)+`,`+
			histRow(2, `\"acc\":0.7,\"loss\":null`)+`,`+
			histRow(3, `\"loss\":1.0,\"_runtime\":4`)+`]}}}`)
	page := query(leet.HistoryQuery{Keys: []string{"loss", "note"}, Limit: 2})
	assert.Equal(t, "remote_history", page["retrieval_method"])
	assert.Equal(t, true, page["exact"])
	assert.Equal(t, "finished", page["state"])
	assert.EqualValues(t, 70, page["total_steps"])
	assert.EqualValues(t, 2, page["rows_scanned"])
	assert.Equal(t, []any{"loss"}, page["keys"])
	assert.Equal(t, map[string]any{"loss": "_step"}, page["axes"])
	assert.Equal(t, map[string]any{"note": "non_numeric"}, page["skipped_keys"])
	assert.Equal(t, []any{
		map[string]any{"_step": 0.0, "_runtime": 1.0, "loss": 1.5},
		map[string]any{"_step": 1.0, "_runtime": 2.0, "loss": 1.25},
	}, page["rows"])
	assert.Equal(t, true, page["has_more"])
	assert.Equal(t, []any{}, page["warnings"])
	coverage := page["coverage"].(map[string]any)
	assert.Equal(t, 0.0, coverage["first_x"])
	assert.Equal(t, 1.0, coverage["last_x"])
	cursor, _ := page["next_cursor"].(string)
	raw, err := base64.RawURLEncoding.DecodeString(cursor)
	require.NoError(t, err)
	assert.JSONEq(t, `{"v":1,"s":2,"f":"abc"}`, string(raw))

	client.StubMatchOnce(gqlmock.WithOpName("QueryRunInfo"), runInfo)
	client.StubMatchOnce(gqlmock.WithOpName("RunParquetHistory"), noParquet)
	client.StubMatchOnce(
		gomock.All(gqlmock.WithOpName("HistoryPage"),
			gqlmock.WithVariables(gqlmock.GQLVar("minStep", gomock.Eq(2.0)))),
		`{"project":{"run":{"history":[`+histRow(2, `\"acc\":0.7,\"loss\":null`)+`,`+
			histRow(3, `\"loss\":1.0,\"_runtime\":4`)+`]}}}`)
	page = query(leet.HistoryQuery{Keys: []string{"loss", "note"}, Limit: 2, After: cursor})
	assert.True(t, client.AllStubsUsed())
	assert.Equal(t, []any{map[string]any{"_step": 3.0, "_runtime": 4.0, "loss": 1.0}}, page["rows"])
	assert.EqualValues(t, 2, page["rows_scanned"])
	assert.Equal(t, false, page["has_more"])
	assert.Nil(t, page["next_cursor"])
	assert.Equal(t, []any{`no key matches "note"`}, page["warnings"])
	assert.Equal(t, map[string]any{}, page["skipped_keys"])

	client.StubMatchOnce(gqlmock.WithOpName("QueryRunInfo"),
		strings.Replace(runInfo, `"state":"finished"`, `"state":"running"`, 1))
	client.StubMatchOnce(gqlmock.WithOpName("RunParquetHistory"), noParquet)
	client.StubMatchOnce(gqlmock.WithOpName("HistoryPage"),
		`{"project":{"run":{"history":[`+histRow(3, `\"loss\":1.0`)+`]}}}`)
	page = query(leet.HistoryQuery{Keys: []string{"loss"}})
	assert.Equal(t, "running", page["state"])
	assert.Equal(t, false, page["has_more"])
	cursor, _ = page["next_cursor"].(string)
	raw, err = base64.RawURLEncoding.DecodeString(cursor)
	require.NoError(t, err)
	assert.JSONEq(t, `{"v":1,"s":4,"f":"abc"}`, string(raw))
}

func TestQueryRemoteHistory_Bins(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(gqlmock.WithOpName("QueryRunInfo"), runInfo)
	client.StubMatchOnce(
		gomock.All(gqlmock.WithOpName("QueryRunBucketedHistory"),
			gqlmock.WithVariables(gqlmock.GQLVar("specs", gomock.Eq([]any{
				`{"bins":3,"keys":["_step","acc","loss"],"minStep":0,"xAxis":"_step"}`,
			})))),
		`{"project":{"run":{"bucketedHistory":[[`+
			`{"bucketSize":30,"_stepMin":0,"_stepMax":29,"accMin":0.1,"accMax":0.5,"accAvg":0.3,`+
			`"accLast":0.5,"accHasNaN":false,"accCount":30,"lossMin":1,"lossMax":2,"lossAvg":1.5,`+
			`"lossLast":1,"lossHasNaN":false,"lossCount":30},`+
			`{"bucketSize":2,"_stepMin":30,"_stepMax":31,"accMin":null,"accMax":null,`+
			`"accAvg":null,"accLast":null,"accHasNaN":true,"lossMin":0.9,"lossMax":0.9,`+
			`"lossAvg":0.9,"lossLast":0.9,"lossHasNaN":false,"lossCount":2},`+
			`{"bucketSize":40,"_stepMin":32,"_stepMax":70,"accAvg":null,"accHasNaN":false,`+
			`"lossMin":0.5,"lossMax":0.8,"lossAvg":0.6,"lossLast":0.5,"lossHasNaN":false,`+
			`"lossCount":40}]]}}}`)
	params := &leet.RemoteRunParams{
		BaseURL: "https://api.wandb.ai", Entity: "e", Project: "p", RunID: "abc",
	}

	var out bytes.Buffer
	minStep := int64(0)
	err := leet.QueryRemoteHistoryWith(leet.NewRemoteClientsForTest(client), params,
		leet.HistoryQuery{Keys: []string{"acc", "loss", "nope*"}, Bins: 3, MinStep: &minStep}, &out)
	obj := remoteQuery(t, &out, err)

	assert.True(t, client.AllStubsUsed())
	assert.Equal(t, "remote_bucketed", obj["retrieval_method"])
	assert.Equal(t, false, obj["exact"])
	assert.EqualValues(t, 70, obj["total_steps"])
	assert.EqualValues(t, 72, obj["rows_scanned"])
	assert.Equal(t, []any{"acc", "loss"}, obj["keys"])
	assert.Equal(t, []any{`no key matches "nope*"`}, obj["warnings"])
	coverage := obj["coverage"].(map[string]any)
	assert.Equal(t, 0.0, coverage["first_x"])
	assert.Equal(t, 70.0, coverage["last_x"])
	assert.EqualValues(t, 0, coverage["requested_min_step"])
	series := obj["series"].([]any)
	require.Len(t, series, 2)
	assert.Equal(t, map[string]any{
		"key": "acc", "x_axis": "_step", "count": 30.0,
		"bins": []any{
			map[string]any{"x0": 0.0, "x1": 29.0, "count": 30.0, "min": 0.1, "max": 0.5,
				"avg": 0.3, "last": 0.5, "has_nan": false},
			map[string]any{"x0": 30.0, "x1": 31.0, "count": 0.0, "min": nil, "max": nil,
				"avg": nil, "last": nil, "has_nan": true},
		},
	}, series[0])
	loss := series[1].(map[string]any)
	assert.EqualValues(t, 72, loss["count"])
	assert.Len(t, loss["bins"], 3)

	client.StubMatchOnce(gqlmock.WithOpName("QueryRunInfo"), runInfo)
	client.StubMatchOnce(
		gomock.All(gqlmock.WithOpName("QueryRunBucketedHistory"),
			gqlmock.WithVariables(gqlmock.GQLVar("specs", gomock.Eq([]any{
				`{"bins":2,"keys":["_runtime","loss"],"maxStep":9,"xAxis":"_runtime"}`,
			})))),
		`{"project":{"run":{"bucketedHistory":[[{"bucketSize":10,"_runtimeMin":0.5,`+
			`"_runtimeMax":9.5,"_runtimeAvg":5,"_runtimeLast":9.5,"_runtimeHasNaN":false,`+
			`"_runtimeCount":10,"lossMin":1,"lossMax":1,"lossAvg":1,"lossLast":1,`+
			`"lossHasNaN":false}]]}}}`)
	out.Reset()
	maxStep := int64(9)
	err = leet.QueryRemoteHistoryWith(leet.NewRemoteClientsForTest(client), params,
		leet.HistoryQuery{
			Keys: []string{"_runtime", "loss"}, Bins: 2, XAxis: "_runtime", MaxStep: &maxStep,
		}, &out)
	obj = remoteQuery(t, &out, err)
	assert.Equal(t, []any{}, obj["warnings"])
	assert.Equal(t, map[string]any{"_runtime": "_runtime", "loss": "_runtime"}, obj["axes"])
	assert.Equal(t, 0.5, obj["coverage"].(map[string]any)["first_x"])
	series = obj["series"].([]any)
	require.Len(t, series, 2)
	assert.Equal(t, "_runtime", series[0].(map[string]any)["key"])
	assert.EqualValues(t, 10, series[0].(map[string]any)["count"])
	assert.EqualValues(t, 1, series[1].(map[string]any)["count"])

	client.StubMatchOnce(gqlmock.WithOpName("QueryRunInfo"), runInfo)
	client.StubMatchOnce(gqlmock.WithOpName("QueryRunBucketedHistory"),
		`{"project":{"run":{"bucketedHistory":[[]]}}}`)
	out.Reset()
	err = leet.QueryRemoteHistoryWith(leet.NewRemoteClientsForTest(client), params,
		leet.HistoryQuery{Keys: []string{"loss"}, Bins: 2, XAxis: "nope"}, &out)
	obj = remoteQuery(t, &out, err)
	assert.True(t, client.AllStubsUsed())
	assert.Equal(t, []any{`x axis "nope" was not found in any row`, `no key matches "loss"`},
		obj["warnings"])
	assert.Equal(t, []any{}, obj["keys"])
	assert.Equal(t, []any{}, obj["series"])
}

func TestQueryRemoteSystem(t *testing.T) {
	client := gqlmock.NewMockClient()
	params := &leet.RemoteRunParams{
		BaseURL: "https://api.wandb.ai", Entity: "e", Project: "p", RunID: "abc",
	}

	err := leet.QueryRemoteSystemWith(leet.NewRemoteClientsForTest(client), params,
		leet.SystemQuery{Last: 5}, &bytes.Buffer{})
	var qerr *leet.QueryError
	require.ErrorAs(t, err, &qerr)
	assert.Equal(t, "not_available", qerr.Code)
	assert.Equal(t, "system metrics of a remote run are served in bins only: pass --bins N",
		qerr.Message)

	client.StubMatchOnce(gqlmock.WithOpName("QueryRunInfo"), strings.Replace(runInfo,
		`"systemMetrics":""`,
		`"systemMetrics":"{\"system.cpu\":1.0,\"system.gpu.0.gpu\":2.0,\"system.memory\":3.0}"`, 1))
	const gpu = "system/gpu.0.gpu"
	client.StubMatchOnce(
		gomock.All(gqlmock.WithOpName("QueryRunBucketedHistory"),
			gqlmock.WithVariables(gqlmock.GQLVar("specs", gomock.Eq([]any{
				`{"bins":2,"keys":["_timestamp","` + gpu + `"],"xAxis":"_timestamp"}`,
			})))),
		`{"project":{"run":{"bucketedHistory":[[`+
			`{"bucketSize":5,"_timestampMin":100,"_timestampMax":104,"`+gpu+`Min":10,"`+gpu+
			`Max":20,"`+gpu+`Avg":15,"`+gpu+`Last":20,"`+gpu+`HasNaN":false,"`+gpu+`Count":5},`+
			`{"bucketSize":5,"_timestampMin":105,"_timestampMax":109,"`+gpu+`Min":30,"`+gpu+
			`Max":40,"`+gpu+`Avg":35,"`+gpu+`Last":40,"`+gpu+`HasNaN":false,"`+gpu+`Count":5}`+
			`]]}}}`)
	var out bytes.Buffer
	err = leet.QueryRemoteSystemWith(leet.NewRemoteClientsForTest(client), params,
		leet.SystemQuery{Keys: []string{"system.gpu.*", "system.nope"}, Bins: 2}, &out)
	obj := remoteQuery(t, &out, err)

	assert.True(t, client.AllStubsUsed())
	assert.Equal(t, "leet.system/1", obj["schema"])
	assert.Equal(t, "remote_bucketed", obj["retrieval_method"])
	assert.Equal(t, []any{"system.gpu.0.gpu"}, obj["keys"])
	assert.Equal(t, []any{`no key matches "system.nope"`}, obj["warnings"])
	assert.EqualValues(t, 10, obj["rows_scanned"])
	coverage := obj["coverage"].(map[string]any)
	assert.Equal(t, 100.0, coverage["first_x"])
	assert.Equal(t, 109.0, coverage["last_x"])
	assert.Nil(t, coverage["requested_since"])
	series := obj["series"].([]any)
	require.Len(t, series, 1)
	entry := series[0].(map[string]any)
	assert.Equal(t, "system.gpu.0.gpu", entry["key"])
	assert.Equal(t, "_timestamp", entry["x_axis"])
	assert.Equal(t, "GPU Utilization", entry["title"])
	assert.Equal(t, "%", entry["unit"])
	assert.EqualValues(t, 10, entry["count"])
	bins := entry["bins"].([]any)
	require.Len(t, bins, 2)
	assert.Equal(t, 100.0, bins[0].(map[string]any)["x0"])
	assert.Equal(t, 105.0, bins[1].(map[string]any)["x0"])
	assert.Equal(t, 35.0, bins[1].(map[string]any)["avg"])
}
