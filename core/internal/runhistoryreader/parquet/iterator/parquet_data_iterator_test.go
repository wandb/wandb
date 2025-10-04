package iterator

import (
	"context"
	"math"
	"os"
	"path/filepath"
	"testing"

	"github.com/apache/arrow-go/v18/arrow"
	"github.com/apache/arrow-go/v18/arrow/memory"
	"github.com/apache/arrow-go/v18/parquet"
	"github.com/apache/arrow-go/v18/parquet/file"
	"github.com/apache/arrow-go/v18/parquet/pqarrow"
	"github.com/apache/arrow-go/v18/parquet/schema"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	test "github.com/wandb/wandb/core/tests/parquet"
)

func getRowIteratorForFile(
	t *testing.T,
	filePath string,
	keys []string,
	config IteratorConfig,
) RowIterator {
	t.Helper()

	pr, err := file.OpenParquetFile(filePath, true)
	require.NoError(t, err)
	r, err := pqarrow.NewFileReader(pr, pqarrow.ArrowReadProperties{}, memory.DefaultAllocator)
	require.NoError(t, err)
	it, err := NewRowIterator(
		context.Background(),
		r,
		keys,
		config,
	)
	require.NoError(t, err)

	t.Cleanup(func() {
		it.Release()
		pr.Close()
	})
	return it
}

func TestRowIterator_WithHistoryPageRange(t *testing.T) {
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			{Name: "loss", Type: arrow.PrimitiveTypes.Int64},
		},
		nil, /* metadata */
	)
	data := []map[string]any{
		{"_step": 1, "loss": 1},
		{"_step": 2, "loss": 2},
		{"_step": 3, "loss": 3},
	}
	filePath := filepath.Join(t.TempDir(), "test.parquet")
	test.CreateTestParquetFileFromData(
		t,
		filePath,
		schema,
		data,
	)
	it := getRowIteratorForFile(
		t,
		filePath,
		[]string{"loss"},
		NewRowFilteredIteratorConfig(StepKey, 0, 2),
		// NewSelectAllRowsIteratorConfig(StepKey),
	)

	next, err := it.Next()
	assert.NoError(t, err)
	assert.True(t, next)
	assert.Equal(t, KeyValueList{{Key: "loss", Value: int64(1)}}, it.Value())

	// Verify no more data returned
	next, err = it.Next()
	assert.NoError(t, err)
	assert.False(t, next, "Expected no more data returned")
}

func TestRowIterator_WithEventsPageRange(t *testing.T) {
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_timestamp", Type: arrow.PrimitiveTypes.Float64},
			{Name: "loss", Type: arrow.PrimitiveTypes.Int64},
			{Name: "_step", Type: arrow.PrimitiveTypes.Float64},
		},
		nil, /* metadata */
	)
	data := []map[string]any{
		{"_timestamp": 1.0, "loss": 1, "_step": 3.0},
		{"_timestamp": 2.0, "loss": 2, "_step": 2.0},
		{"_timestamp": 3.0, "loss": 3, "_step": 1.0},
	}
	filePath := filepath.Join(t.TempDir(), "test.parquet")
	test.CreateTestParquetFileFromData(
		t,
		filePath,
		schema,
		data,
	)
	it := getRowIteratorForFile(
		t,
		filePath,
		[]string{"loss"},
		NewRowFilteredIteratorConfig(TimestampKey, 0.0, 2.0),
	)

	next, err := it.Next()
	assert.NoError(t, err)
	assert.True(t, next)
	assert.Equal(t, KeyValueList{{Key: "loss", Value: int64(1)}}, it.Value())

	// Verify no more data returned
	next, err = it.Next()
	assert.NoError(t, err)
	assert.False(t, next, "Expected no more data returned")
}

func TestRowIterator_ReleaseFreesMemory(t *testing.T) {
	allocator := memory.NewCheckedAllocator(memory.DefaultAllocator)
	defer allocator.AssertSize(t, 0)

	filePath := "../../../../tests/files/history.parquet"
	it := getRowIteratorForFile(
		t,
		filePath,
		[]string{"_step"},
		NewSelectAllRowsIteratorConfig(StepKey),
	)

	next, err := it.Next()
	i := 0
	for ; next && err == nil; next, err = it.Next() {
		assert.NoError(t, err)
		assert.True(t, next)
		assert.Equal(
			t,
			KeyValueList{{Key: "_step", Value: float64(i)}},
			it.Value(),
		)
		i++
	}

	it.Release()
	allocator.AssertSize(t, 0)
}

func TestRowIterator_EmptyFile(t *testing.T) {
	allocator := memory.NewCheckedAllocator(memory.DefaultAllocator)
	filePath := "../../../../tests/files/empty.parquet"
	f, err := os.Open(filePath)
	if err != nil {
		t.Fatal(err)
	}
	pf, err := file.NewParquetReader(
		f,
		file.WithReadProps(parquet.NewReaderProperties(allocator)),
	)
	if err != nil {
		t.Fatal(err)
	}
	defer pf.Close()

	r, err := pqarrow.NewFileReader(pf, pqarrow.ArrowReadProperties{}, allocator)
	if err != nil {
		t.Fatal(err)
	}

	// all row groups should be read
	ctx := context.Background()
	config := NewSelectAllRowsIteratorConfig(StepKey)
	it, err := NewRowIterator(ctx, r, []string{"_step"}, config)
	if err != nil {
		t.Fatal(err)
	}

	hasRow, err := it.Next()
	if err != nil {
		t.Fatal(err)
	}
	if hasRow {
		t.Fatal("found row in empty parquet file")
	}
}

func TestRowIterator_WithMissingColumns(t *testing.T) {
	schema := arrow.NewSchema([]arrow.Field{
		{Name: "_step", Type: arrow.PrimitiveTypes.Float64},
		{Name: "loss", Type: arrow.PrimitiveTypes.Int64},
	}, nil)
	data := []map[string]any{
		{"_step": 1.0, "loss": 1},
		{"_step": 2.0, "loss": 2},
	}
	filePath := filepath.Join(t.TempDir(), "test.parquet")
	test.CreateTestParquetFileFromData(t, filePath, schema, data)

	pr, err := file.OpenParquetFile(filePath, true)
	require.NoError(t, err)
	r, err := pqarrow.NewFileReader(pr, pqarrow.ArrowReadProperties{}, memory.DefaultAllocator)
	require.NoError(t, err)

	_, err = NewRowIterator(
		context.Background(),
		r,
		[]string{"_step", "loss", "nonexistent_column"},
		NewRowFilteredIteratorConfig(StepKey, 0, 2),
	)

	assert.Error(t, err)
	assert.ErrorContains(t, err, "column nonexistent_column selected but not found")
}

func TestRowIterator_WithComplexColumns(t *testing.T) {
	schema := arrow.NewSchema([]arrow.Field{
		{Name: "_step", Type: arrow.PrimitiveTypes.Float64},
		{Name: "loss", Type: arrow.PrimitiveTypes.Int64},
		{Name: "nested", Type: arrow.StructOf(
			arrow.Field{Name: "nested_a", Type: arrow.PrimitiveTypes.Float64},
			arrow.Field{Name: "nested_b", Type: arrow.PrimitiveTypes.Float64},
		)},
	}, nil)
	data := []map[string]any{
		{
			"_step":  1.0,
			"loss":   int64(1),
			"nested": map[string]any{"nested_a": 1.0, "nested_b": 2.0},
		},
		{
			"_step":  2.0,
			"loss":   int64(2),
			"nested": map[string]any{"nested_a": 2.0, "nested_b": 4.0},
		},
		{
			"_step":  3.0,
			"loss":   int64(3),
			"nested": map[string]any{"nested_a": 4.0, "nested_b": 6.0},
		},
	}
	tempFile := filepath.Join(t.TempDir(), "test_list_of_structs.parquet")
	test.CreateTestParquetFileFromData(t, tempFile, schema, data)
	it := getRowIteratorForFile(
		t,
		tempFile,
		[]string{},
		NewRowFilteredIteratorConfig(StepKey, 0, math.MaxInt64),
	)

	// Verify all rows match the input data
	for i, row := range data {
		next, err := it.Next()
		assert.NoError(t, err, "Error getting row %d", i)
		assert.True(t, next, "Expected row %d to exist", i)

		// Build expected KVMapList from the data row
		// The order should match how the iterator returns columns
		expectedRow := KeyValueList{
			{Key: "_step", Value: row["_step"]},
			{Key: "loss", Value: row["loss"]},
			{Key: "nested", Value: row["nested"]},
		}

		assert.Equal(t, expectedRow, it.Value(), "Row %d mismatch", i)
	}

	// Verify no more rows beyond what's in the data
	next, err := it.Next()
	assert.NoError(t, err)
	assert.False(t, next, "Expected no more rows after %d rows", len(data))
}

func TestSelectColumns(t *testing.T) {
	// Create a simple schema with 4 columns
	fields := []schema.Node{
		schema.NewInt64Node("_step", parquet.Repetitions.Required, -1),
		schema.NewFloat64Node("loss", parquet.Repetitions.Optional, -1),
		schema.MustPrimitive(schema.NewPrimitiveNode("metric", parquet.Repetitions.Optional, parquet.Types.ByteArray, int32(schema.ConvertedTypes.UTF8), -1)),
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
			columns:     []string{"_step", "loss"},
			wantIndices: []int{0, 1},
			wantErr:     false,
		},
		{
			name:        "select single column",
			columns:     []string{"metric"},
			wantIndices: []int{2},
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
		t.Run(tt.name, func(t *testing.T) {
			selectedColumns, err := SelectOnlyColumns(tt.columns, s)

			if tt.wantErr {
				assert.Error(t, err)
			} else {
				indices := selectedColumns.GetColumnIndices()
				assert.NoError(t, err)
				assert.Equal(t, tt.wantIndices, indices)
			}
		})
	}
}
