package iterator

import (
	"testing"

	"github.com/apache/arrow-go/v18/parquet"
	"github.com/apache/arrow-go/v18/parquet/schema"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestSelectColumns(t *testing.T) {
	// Create a simple schema with 4 columns
	fields := []schema.Node{
		schema.NewInt64Node("_step", parquet.Repetitions.Required, -1),
		schema.NewFloat64Node("loss", parquet.Repetitions.Optional, -1),
		schema.MustPrimitive(
			schema.NewPrimitiveNode(
				"metric",
				parquet.Repetitions.Optional,
				parquet.Types.ByteArray,
				int32(schema.ConvertedTypes.UTF8),
				-1,
			),
		),
		schema.NewInt64Node("timestamp", parquet.Repetitions.Required, -1),
	}
	testSchema, err := schema.NewGroupNode("schema", parquet.Repetitions.Required, fields, -1)
	require.NoError(t, err)
	s := schema.NewSchema(testSchema)

	tests := []struct {
		name        string
		columns     []string
		wantIndices []int
		wantErr     bool
	}{
		{
			name:        "select specific columns",
			columns:     []string{"_step", "loss", "metric"},
			wantIndices: []int{0, 1, 2},
			wantErr:     false,
		},
		{
			name:        "select single column",
			columns:     []string{"metric"},
			wantIndices: []int{0, 2},
			wantErr:     false,
		},
		{
			name:        "error on non-existent column",
			columns:     []string{"nonexistent"},
			wantIndices: nil,
			wantErr:     true,
		},
		{
			name:        "mix of existing and non-existing columns",
			columns:     []string{"_step", "nonexistent"},
			wantIndices: nil,
			wantErr:     true,
		},
	}

	for _, tt := range tests {
		selectAllColumns := len(tt.columns) == 0
		t.Run(tt.name, func(t *testing.T) {
			selectedColumns, err := SelectColumns(
				StepKey,
				tt.columns,
				s,
				selectAllColumns,
			)

			if tt.wantErr {
				assert.Error(t, err)
			} else {
				indices := selectedColumns.GetColumnIndices()
				assert.NoError(t, err)
				assert.ElementsMatch(t, tt.wantIndices, indices)
			}
		})
	}
}
