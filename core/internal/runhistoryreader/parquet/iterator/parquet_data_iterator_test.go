package iterator

import (
	"context"
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
	indexKey string,
	minValue float64,
	maxValue float64,
	selectAll bool,
) RowIterator {
	t.Helper()

	pr, err := file.OpenParquetFile(filePath, true)
	require.NoError(t, err)
	r, err := pqarrow.NewFileReader(pr, pqarrow.ArrowReadProperties{}, memory.DefaultAllocator)
	require.NoError(t, err)

	selectedRows := SelectRows(r, indexKey, minValue, maxValue, selectAll)
	selectedColumns, err := SelectColumns(
		indexKey,
		keys,
		r.ParquetReader().MetaData().Schema,
	)
	require.NoError(t, err)


	it, err := NewRowIterator(
		context.Background(),
		r,
		selectedRows,
		selectedColumns,
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
		{"_step": int64(1), "loss": int64(1)},
		{"_step": int64(2), "loss": int64(2)},
		{"_step": int64(3), "loss": int64(3)},
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
		StepKey,
		0,
		2,
		false,
	)

	next, err := it.Next()
	assert.NoError(t, err)
	assert.True(t, next)
	expectedValue := data[0]
	for _, kvPair := range it.Value() {
		assert.Equal(t, expectedValue[kvPair.Key], kvPair.Value)
	}

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
		{"_timestamp": 1.0, "loss": int64(1), "_step": 3.0},
		{"_timestamp": 2.0, "loss": int64(2), "_step": 2.0},
		{"_timestamp": 3.0, "loss": int64(3), "_step": 1.0},
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
		TimestampKey,
		0.0,
		2.0,
		false,
	)

	next, err := it.Next()
	assert.NoError(t, err)
	assert.True(t, next)
	expectedValue := data[0]
	for _, kvPair := range it.Value() {
		assert.Equal(t, expectedValue[kvPair.Key], kvPair.Value)
	}

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
		StepKey,
		0,
		0,
		true,
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

// TODO: move this to parquet_data_selector_test.go
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
	_, err = SelectColumns(StepKey, []string{"_step"}, r.ParquetReader().MetaData().Schema)
	require.Error(t, err)
	// it, err := NewRowIterator(ctx, r, selectedRows, selectedColumns)
	// require.NoError(t, err)
	//
	// next, err := it.Next()
	// require.NoError(t, err)
	// assert.False(t, next, "Expected no more rows")
}

// TODO: move this to parquet_data_selector_test.go
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

	_, err = SelectColumns(
		StepKey,
		[]string{"_step", "loss", "nonexistent_column"},
		r.ParquetReader().MetaData().Schema,
	)

	assert.Error(t, err)
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
		StepKey,
		0,
		0,
		true,
	)

	// Verify all rows match the input data
	for i, row := range data {
		next, err := it.Next()
		assert.NoError(t, err, "Error getting row %d", i)
		assert.True(t, next, "Expected row %d to exist", i)

		val := it.Value()
		for _, kv := range val {
			assert.Equal(t, row[kv.Key], kv.Value)
		}
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
		t.Run(tt.name, func(t *testing.T) {
			selectedColumns, err := SelectColumns(
				StepKey,
				tt.columns,
				s,
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
