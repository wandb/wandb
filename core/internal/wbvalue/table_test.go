package wbvalue_test

import (
	"math"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/wbvalue"
)

func TestTableFileContent(t *testing.T) {
	table := wbvalue.Table{
		Rows: [][]any{
			{1, 14.5, false, "abc"},
			{2, math.NaN(), true, "xyz"},
			{3, math.Inf(1), true, "tuv"},
		},
		ColumnLabels: []string{"int", "float", "bool", "string"},
	}

	content, err := table.FileContent()

	require.NoError(t, err)
	contentMap, _ := simplejsonext.UnmarshalObject(content)
	assert.Equal(t,
		[]any{"int", "float", "bool", "string"},
		contentMap["columns"])
	data := contentMap["data"].([]any)
	assert.Equal(t,
		[]any{int64(1), 14.5, false, "abc"},
		data[0])
	assert.True(t, math.IsNaN(data[1].([]any)[1].(float64)))
	assert.True(t, math.IsInf(data[2].([]any)[1].(float64), 1))
}

func TestTableHistoryJSON(t *testing.T) {
	table := wbvalue.Table{
		Rows: [][]any{
			{1, 14.5, false, "abc"},
			{2, math.NaN(), true, "xyz"},
			{3, math.Inf(1), true, "tuv"},
		},
		ColumnLabels: []string{"int", "float", "bool", "string"},
	}

	metadataJSON, err := table.HistoryValueJSON(
		paths.RelativePath("a/b/c"),
		"test-hash",
		1234,
	)

	require.NoError(t, err)
	assert.JSONEq(t,
		`{
			"_type": "table-file",
			"ncols": 4,
			"nrows": 3,
			"sha256": "test-hash",
			"size": 1234,
			"path": "a/b/c"
		}`,
		metadataJSON)
}
