package leetmcp_test

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const appsCapabilities = `{"extensions":{"io.modelcontextprotocol/ui":` +
	`{"mimeTypes":["text/html;profile=mcp-app"]}}}`

var viewMeta = map[string]any{"ui": map[string]any{"resourceUri": "ui://leet/panel"}}

// toolsByName indexes the tools of a tools/list response by name.
func toolsByName(t *testing.T, resp map[string]any) map[string]map[string]any {
	tools := map[string]map[string]any{}
	for _, tool := range result(t, resp)["tools"].([]any) {
		tool := tool.(map[string]any)
		tools[tool["name"].(string)] = tool
	}
	return tools
}

func TestServe_PanelForClientsThatRenderApps(t *testing.T) {
	resps := serve(t,
		`{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25",`+
			`"capabilities":`+appsCapabilities+`}}`,
		`{"jsonrpc":"2.0","id":2,"method":"tools/list"}`,
		`{"jsonrpc":"2.0","id":3,"method":"resources/list"}`,
		`{"jsonrpc":"2.0","id":4,"method":"resources/read","params":{"uri":"ui://leet/panel"}}`,
	)
	require.Len(t, resps, 4)

	tools := toolsByName(t, resps[1])
	require.Contains(t, tools, "leet_view")
	assert.Equal(t, viewMeta, tools["leet_view"]["_meta"])
	delete(tools, "leet_view")
	for name, tool := range tools {
		assert.NotContains(t, tool, "_meta", name)
	}

	prefersBorder := map[string]any{"ui": map[string]any{"prefersBorder": true}}
	resources := result(t, resps[2])["resources"].([]any)
	require.Len(t, resources, 1)
	resource := resources[0].(map[string]any)
	assert.Equal(t, "ui://leet/panel", resource["uri"])
	assert.Equal(t, "text/html;profile=mcp-app", resource["mimeType"])
	assert.Equal(t, prefersBorder, resource["_meta"])

	contents := result(t, resps[3])["contents"].([]any)
	require.Len(t, contents, 1)
	content := contents[0].(map[string]any)
	assert.Equal(t, "ui://leet/panel", content["uri"])
	assert.Equal(t, "text/html;profile=mcp-app", content["mimeType"])
	assert.Equal(t, prefersBorder, content["_meta"])
	html := content["text"].(string)
	assert.True(t, strings.HasPrefix(html, "<!DOCTYPE html>"))
	assert.True(t, strings.HasSuffix(strings.TrimSpace(html), "</html>"))
}

func TestServe_NoPanelWithoutApps(t *testing.T) {
	appsMeta := `"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",` +
		`"io.modelcontextprotocol/clientCapabilities":` + appsCapabilities + `}`
	resps := serve(t,
		`{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25",`+
			`"capabilities":{"extensions":{"io.modelcontextprotocol/ui":`+
			`{"mimeTypes":["text/html"]}}}}}`,
		`{"jsonrpc":"2.0","id":2,"method":"tools/list"}`,
		`{"jsonrpc":"2.0","id":3,"method":"resources/list"}`,
		`{"jsonrpc":"2.0","id":4,"method":"resources/read","params":{"uri":"ui://leet/panel"}}`,
		`{"jsonrpc":"2.0","id":5,"method":"resources/read","params":{"uri":"ui://leet/panel",`+
			modernMeta+`}}`,
		`{"jsonrpc":"2.0","id":6,"method":"resources/read","params":{"uri":"ui://leet/panel",`+
			appsMeta+`}}`,
		`{"jsonrpc":"2.0","id":7,"method":"tools/list","params":{`+appsMeta+`}}`,
	)
	require.Len(t, resps, 7)

	for _, tool := range result(t, resps[1])["tools"].([]any) {
		assert.NotContains(t, tool.(map[string]any), "_meta")
	}
	assert.Equal(t, []any{}, result(t, resps[2])["resources"])
	assert.EqualValues(t, -32002, rpcError(t, resps[3])["code"])
	assert.EqualValues(t, -32602, rpcError(t, resps[4])["code"])
	assert.Len(t, result(t, resps[5])["contents"], 1)
	tools := toolsByName(t, resps[6])
	require.Contains(t, tools, "leet_view")
	assert.Equal(t, viewMeta, tools["leet_view"]["_meta"])
}

func TestServe_ViewTool(t *testing.T) {
	wandbDir := filepath.Join(t.TempDir(), "wandb")
	for i, id := range []string{"a", "b"} {
		dir := filepath.Join(wandbDir, "run-20250101_00000"+string(rune('1'+i))+"-"+id)
		require.NoError(t, os.MkdirAll(dir, 0o755))
		w, err := transactionlog.OpenWriter(filepath.Join(dir, "run-"+id+".wandb"))
		require.NoError(t, err)
		require.NoError(t, w.Write(&spb.Record{RecordType: &spb.Record_Run{
			Run: &spb.RunRecord{RunId: id, DisplayName: "run " + id},
		}}))
		require.NoError(t, w.Close())
	}

	call := func(arguments map[string]any) map[string]any {
		arguments["path"] = wandbDir
		args, _ := json.Marshal(arguments)
		resps := serve(t, `{"jsonrpc":"2.0","id":1,"method":"tools/call",`+
			`"params":{"name":"leet_view","arguments":`+string(args)+`}}`)
		require.Len(t, resps, 1)
		res := result(t, resps[0])
		require.Equal(t, false, res["isError"], res)
		return res["structuredContent"].(map[string]any)
	}

	content := call(map[string]any{"keys": []string{"loss"}})
	assert.Equal(t, "leet.view/1", content["schema"])
	assert.Equal(t, map[string]any{
		"filter": "", "glob": false, "keys": []any{"loss"}, "x_axis": "_step", "bins": float64(200),
	}, content["view"])
	runs := content["runs"].(map[string]any)
	assert.Equal(t, "leet.runs/1", runs["schema"])
	assert.EqualValues(t, 2, runs["total"])
	assert.Equal(t, "run b", runs["runs"].([]any)[0].(map[string]any)["name"])

	content = call(map[string]any{"filter": "name:b", "bins": 50})
	assert.Equal(t, map[string]any{
		"filter": "name:b", "glob": false, "keys": []any{}, "x_axis": "_step", "bins": float64(50),
	}, content["view"])
	assert.EqualValues(t, 1, content["runs"].(map[string]any)["total"])
}
