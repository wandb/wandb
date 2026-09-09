package remote

import (
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/gqlmock"
)

func consoleLogsPageResp(
	logLineCount any,
	edges []map[string]any,
	hasNextPage bool,
	endCursor string,
) string {
	resp := map[string]any{
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
	b, err := json.Marshal(resp)
	if err != nil {
		panic(err)
	}
	return string(b)
}

func consoleLogEdge(number int, line, level string) map[string]any {
	return map[string]any{
		"node": map[string]any{
			"number":    number,
			"timestamp": "2026-01-01T12:34:56Z",
			"level":     level,
			"label":     "",
			"line":      line,
		},
	}
}

func TestConsoleLogReader_ReadPage(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunConsoleLogPage"),
		consoleLogsPageResp(2, []map[string]any{
			consoleLogEdge(0, "hello", ""),
			consoleLogEdge(1, "world", "error"),
		}, false, "cursor-1"),
	)

	reader := NewConsoleLogReader(mockGQL, "entity", "project", "run-id")

	lines, err := reader.ReadPage(t.Context())
	require.NoError(t, err)
	require.Len(t, lines, 2)
	assert.Equal(t, "hello", lines[0].Content)
	assert.False(t, lines[0].IsStderr)
	assert.Equal(t, "world", lines[1].Content)
	assert.True(t, lines[1].IsStderr)
	assert.False(t, reader.HasMore())

	lines, err = reader.ReadPage(t.Context())
	require.NoError(t, err)
	assert.Empty(t, lines)
}

func TestConsoleLogReader_Paginates(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunConsoleLogPage"),
		consoleLogsPageResp(2, []map[string]any{
			consoleLogEdge(0, "first", ""),
		}, true, "cursor-1"),
	)
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunConsoleLogPage"),
		consoleLogsPageResp(2, []map[string]any{
			consoleLogEdge(1, "second", ""),
		}, false, "cursor-2"),
	)

	reader := NewConsoleLogReader(mockGQL, "entity", "project", "run-id")

	lines, err := reader.ReadPage(t.Context())
	require.NoError(t, err)
	require.Len(t, lines, 1)
	assert.Equal(t, "first", lines[0].Content)
	assert.True(t, reader.HasMore())

	lines, err = reader.ReadPage(t.Context())
	require.NoError(t, err)
	require.Len(t, lines, 1)
	assert.Equal(t, "second", lines[0].Content)
	assert.False(t, reader.HasMore())
}

func TestParseConsoleLogTimestamp(t *testing.T) {
	ts := parseConsoleLogTimestamp("2026-01-01T12:34:56.123456Z")
	assert.Equal(t, 2026, ts.Year())
	assert.Equal(t, 12, int(ts.Hour()))

	ts = parseConsoleLogTimestamp("2026-01-01T12:34:56")
	assert.False(t, ts.IsZero())
	assert.Equal(t, 12, int(ts.Hour()))

	assert.True(t, parseConsoleLogTimestamp("").IsZero())
	assert.True(t, parseConsoleLogTimestamp("not-a-time").IsZero())
}
