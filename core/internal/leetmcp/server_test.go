package leetmcp_test

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/leetmcp"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const modernMeta = `"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",` +
	`"io.modelcontextprotocol/clientCapabilities":{}}`

// serve answers the request lines on a fresh server, which must stop at the
// end of its input without an error, and returns the decoded responses.
func serve(t *testing.T, lines ...string) []map[string]any {
	t.Helper()
	var stdout, stderr bytes.Buffer
	stdin := strings.NewReader(strings.Join(lines, "\n") + "\n")
	require.NoError(t, leetmcp.Serve(stdin, &stdout, &stderr))

	var responses []map[string]any
	for line := range strings.Lines(stdout.String()) {
		var resp map[string]any
		require.NoError(t, json.Unmarshal([]byte(line), &resp), line)
		responses = append(responses, resp)
	}
	return responses
}

func result(t *testing.T, resp map[string]any) map[string]any {
	t.Helper()
	require.Nil(t, resp["error"])
	return resp["result"].(map[string]any)
}

func rpcError(t *testing.T, resp map[string]any) map[string]any {
	t.Helper()
	require.Nil(t, resp["result"])
	return resp["error"].(map[string]any)
}

func TestServe_LegacyHandshake(t *testing.T) {
	resps := serve(t,
		`{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25",`+
			`"capabilities":{},"clientInfo":{"name":"test","version":"1"}}}`,
		`{"jsonrpc":"2.0","method":"notifications/initialized"}`,
		`{"jsonrpc":"2.0","id":2,"method":"initialize","params":{"protocolVersion":"2026-07-28"}}`,
		`{"jsonrpc":"2.0","id":3,"method":"tools/list"}`,
	)
	require.Len(t, resps, 3)

	initialize := result(t, resps[0])
	assert.Equal(t, "2025-11-25", initialize["protocolVersion"])
	assert.Equal(t, "wandb", initialize["serverInfo"].(map[string]any)["name"])
	assert.Equal(t, "2025-11-25", result(t, resps[1])["protocolVersion"])
	assert.NotContains(t, result(t, resps[2]), "resultType")

	byName := make(map[string]map[string]any)
	for _, tool := range result(t, resps[2])["tools"].([]any) {
		tool := tool.(map[string]any)
		byName[tool["name"].(string)] = tool
		props := tool["inputSchema"].(map[string]any)["properties"].(map[string]any)
		for name, prop := range props {
			assert.NotEmpty(t, prop.(map[string]any)["description"], tool["name"], name)
		}
	}

	history := byName["leet_history"]["inputSchema"].(map[string]any)
	props := history["properties"].(map[string]any)
	assert.Equal(t, "array", props["keys"].(map[string]any)["type"])
	assert.Equal(t, map[string]any{"type": "string"}, props["keys"].(map[string]any)["items"])
	assert.Equal(t, "integer", props["bins"].(map[string]any)["type"])
	assert.Equal(t, "integer", props["min_step"].(map[string]any)["type"])
	assert.Contains(t, props, "run")
	assert.NotContains(t, props, "follow")
	assert.Equal(t, []any{"keys"}, history["required"])
	assert.Equal(t, map[string]any{
		"readOnlyHint": true, "destructiveHint": false, "openWorldHint": false,
	}, byName["leet_history"]["annotations"])

	runs := byName["leet_runs"]["inputSchema"].(map[string]any)
	assert.NotContains(t, runs["properties"], "run")
	assert.NotContains(t, runs, "required")

	session := byName["leet_session"]["inputSchema"].(map[string]any)
	method := session["properties"].(map[string]any)["method"].(map[string]any)
	assert.ElementsMatch(t, leet.ControlMethods, method["enum"])
	assert.Equal(t, []any{"method"}, session["required"])
	assert.Equal(t, false, byName["leet_session"]["annotations"].(map[string]any)["readOnlyHint"])
}

func TestServe_ModernRequests(t *testing.T) {
	runsArgs, _ := json.Marshal(map[string]any{"path": t.TempDir()})
	resps := serve(t,
		`{"jsonrpc":"2.0","id":"a","method":"server/discover","params":{`+modernMeta+`}}`,
		`{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"leet_runs",`+
			`"arguments":`+string(runsArgs)+`,`+modernMeta+`}}`,
		`{"jsonrpc":"2.0","id":3,"method":"ping","params":{"_meta":`+
			`{"io.modelcontextprotocol/protocolVersion":"1900-01-01",`+
			`"io.modelcontextprotocol/clientCapabilities":{}}}}`,
		`{"jsonrpc":"2.0","id":4,"method":"ping","params":{"_meta":`+
			`{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}}}`,
		`{"jsonrpc":"2.0","id":5,"method":"resources/read","params":{"uri":"ui://x",`+
			modernMeta+`}}`,
		`{"jsonrpc":"2.0","id":6,"method":"resources/read","params":{"uri":"ui://x"}}`,
	)
	require.Len(t, resps, 6)
	supported := []any{"2026-07-28", "2025-11-25", "2025-06-18"}

	assert.Equal(t, "a", resps[0]["id"])
	discover := result(t, resps[0])
	assert.Equal(t, supported, discover["supportedVersions"])
	assert.Equal(t, "complete", discover["resultType"])
	serverInfo := discover["_meta"].(map[string]any)["io.modelcontextprotocol/serverInfo"]
	assert.Equal(t, "wandb", serverInfo.(map[string]any)["name"])

	call := result(t, resps[1])
	assert.Equal(t, "complete", call["resultType"])
	assert.Equal(t, false, call["isError"])

	rpcErr := rpcError(t, resps[2])
	assert.EqualValues(t, -32022, rpcErr["code"])
	assert.Equal(t, supported, rpcErr["data"].(map[string]any)["supported"])
	assert.EqualValues(t, -32602, rpcError(t, resps[3])["code"])
	assert.EqualValues(t, -32602, rpcError(t, resps[4])["code"])
	assert.EqualValues(t, -32002, rpcError(t, resps[5])["code"])
}

func TestServe_ToolsCall(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run-abc.wandb")
	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	for step := range int64(3) {
		require.NoError(t, w.Write(&spb.Record{RecordType: &spb.Record_History{
			History: &spb.HistoryRecord{
				Step: &spb.HistoryStep{Num: step},
				Item: []*spb.HistoryItem{
					{Key: "loss", ValueJson: "1.5"},
					{Key: "acc", ValueJson: "0.5"},
				},
			},
		}}))
	}
	require.NoError(t, w.Close())

	call := func(arguments map[string]any) map[string]any {
		if _, ok := arguments["path"]; !ok {
			arguments["path"] = path
		}
		args, _ := json.Marshal(arguments)
		resps := serve(t, `{"jsonrpc":"2.0","id":1,"method":"tools/call",`+
			`"params":{"name":"leet_history","arguments":`+string(args)+`}}`)
		require.Len(t, resps, 1)
		return result(t, resps[0])
	}

	res := call(map[string]any{"keys": []string{"loss", "acc"}})
	assert.Equal(t, false, res["isError"])
	content := res["structuredContent"].(map[string]any)
	assert.Equal(t, "leet.history/1", content["schema"])
	assert.Equal(t, []any{"acc", "loss"}, content["keys"])
	assert.Len(t, content["rows"], 3)
	text := res["content"].([]any)[0].(map[string]any)["text"].(string)
	assert.Contains(t, text, `"schema":"leet.history/1"`)

	for _, bad := range []map[string]any{
		{"keys": []string{"loss"}, "bins": 2, "last": 1},
		{"keyz": []string{"loss"}},
		{"keys": []string{"loss"}, "follow": true},
	} {
		res := call(bad)
		assert.Equal(t, true, res["isError"])
		assert.Equal(t, "bad_request", res["structuredContent"].(map[string]any)["error"])
	}

	res = call(map[string]any{"keys": "loss"})
	assert.Equal(t, "keys has the wrong type", res["structuredContent"].(map[string]any)["message"])

	res = call(map[string]any{"keys": []string{"loss"}, "path": "https://wandb.ai/e/p/runs/x"})
	assert.Equal(t, "not_available", res["structuredContent"].(map[string]any)["error"])
}

func TestServe_SessionPath(t *testing.T) {
	tmp, err := filepath.EvalSymlinks(t.TempDir())
	require.NoError(t, err)
	wandbDir := filepath.Join(tmp, "wandb")
	runDir := filepath.Join(wandbDir, "run-20260611_143629-7pkb4mck")
	require.NoError(t, os.MkdirAll(runDir, 0o755))
	require.NoError(t, os.Symlink(runDir, filepath.Join(wandbDir, "latest-run")))

	call := func(path string) map[string]any {
		args, _ := json.Marshal(map[string]any{"path": path, "method": "status"})
		resps := serve(t, `{"jsonrpc":"2.0","id":1,"method":"tools/call",`+
			`"params":{"name":"leet_session","arguments":`+string(args)+`}}`)
		require.Len(t, resps, 1)
		return result(t, resps[0])["structuredContent"].(map[string]any)
	}

	res := call(filepath.Join(wandbDir, "latest-run"))
	assert.Equal(t, "no_session", res["error"])
	assert.Contains(t, res["message"], `"`+wandbDir+`"`)
	assert.Equal(t, "path_not_found", call(filepath.Join(wandbDir, "nope"))["error"])
}

func TestServe_ParseErrorThenContinues(t *testing.T) {
	resps := serve(t,
		`not json`,
		`[{"jsonrpc":"2.0","id":1,"method":"ping"}]`,
		`{"jsonrpc":"2.0","id":8,"method":"ping","params":"x"}`,
		`{"jsonrpc":"2.0","id":9,"method":5}`,
		`null`,
		`{"jsonrpc":"2.0","id":null,"method":"ping"}`,
		`{"jsonrpc":"2.0","id":7,"method":"ping"}`,
	)
	require.Len(t, resps, 7)

	assert.EqualValues(t, -32700, rpcError(t, resps[0])["code"])
	assert.Nil(t, resps[0]["id"])
	assert.EqualValues(t, -32600, rpcError(t, resps[1])["code"])
	assert.Nil(t, resps[1]["id"])
	assert.EqualValues(t, 8, resps[2]["id"])
	assert.Equal(t, map[string]any{"code": float64(-32602), "message": "params must be an object"},
		rpcError(t, resps[2]))
	assert.EqualValues(t, 9, resps[3]["id"])
	assert.Equal(t, map[string]any{"code": float64(-32600), "message": "method has the wrong type"},
		rpcError(t, resps[3]))
	assert.Equal(t, map[string]any{"code": float64(-32600), "message": "request must be an object"},
		rpcError(t, resps[4]))
	assert.Nil(t, resps[4]["id"])
	assert.Equal(t, map[string]any{
		"code": float64(-32600), "message": "id must be a string or a number",
	}, rpcError(t, resps[5]))
	assert.Nil(t, resps[5]["id"])
	assert.EqualValues(t, 7, resps[6]["id"])
	assert.Equal(t, map[string]any{}, result(t, resps[6]))
}
