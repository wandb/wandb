package historyparquet

import (
	"context"
	"math"
	"os"
	"path/filepath"
	"testing"

	"github.com/apache/arrow-go/v18/arrow"
	"github.com/apache/arrow-go/v18/arrow/array"
	"github.com/apache/arrow-go/v18/arrow/memory"
	"github.com/apache/arrow-go/v18/parquet"
	"github.com/apache/arrow-go/v18/parquet/file"
	"github.com/apache/arrow-go/v18/parquet/pqarrow"
	"github.com/apache/arrow-go/v18/parquet/schema"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	test "github.com/wandb/wandb/core/tests/parquet"
)

// testRowIteratorSetup is a helper struct that contains common test setup
type testRowIteratorSetup struct {
	ctx      context.Context
	iterator RowIterator
	reader   *pqarrow.FileReader
	pr       *file.Reader
	filePath string
}

// setupTestRowIterator creates a test parquet file and initializes a row iterator for testing
func setupTestRowIterator(
	t *testing.T,
	schema *arrow.Schema,
	arrays []arrow.Array,
	columns []string,
	opt RowIteratorOption,
) *testRowIteratorSetup {
	t.Helper()

	ctx := context.Background()
	historyFilePath := filepath.Join(t.TempDir(), "test.parquet")
	test.CreateTestParquetFile(t, historyFilePath, schema, arrays)

	pr, err := file.OpenParquetFile(historyFilePath, true)
	require.NoError(t, err)

	reader, err := pqarrow.NewFileReader(
		pr,
		pqarrow.ArrowReadProperties{},
		memory.DefaultAllocator,
	)
	require.NoError(t, err)

	it, err := NewRowIterator(ctx, reader, columns, opt)
	require.NoError(t, err)

	return &testRowIteratorSetup{
		ctx:      ctx,
		iterator: it,
		reader:   reader,
		pr:       pr,
		filePath: historyFilePath,
	}
}

// cleanup properly closes all resources
func (s *testRowIteratorSetup) cleanup() {
	if s.iterator != nil {
		s.iterator.Release()
	}
	if s.pr != nil {
		s.pr.Close()
	}
}

func TestSelectRowGroups(t *testing.T) {
	t.Parallel()
	allocator := memory.NewCheckedAllocator(memory.DefaultAllocator)
	filePath := "../../../../tests/files/history.parquet"
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
	page := HistoryPageParams{
		MinStep: 0,
		MaxStep: 999,
		Samples: 10,
	}
	it, err := NewRowIterator(ctx, r, []string{"_step"}, WithHistoryPageRange(page))
	if err != nil {
		t.Fatal(err)
	}
	assert.Equal(t, 5, len(it.RowGroupIndices()))

	// only row groups within the requested step range should be read
	page.MaxStep = 500
	it, err = NewRowIterator(ctx, r, []string{"_step"}, WithHistoryPageRange(page))
	if err != nil {
		t.Fatal(err)
	}
	assert.Equal(t, 3, len(it.RowGroupIndices()))
}

func TestRowIteratorWithPage(t *testing.T) {
	t.Parallel()

	// Define schema for test parquet file
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			{Name: "loss", Type: arrow.PrimitiveTypes.Int64}, // Note: using Int64 to match the test expectations
		},
		nil,
	)
	arrays := []arrow.Array{
		test.BuildArray(t, []int64{1, 2, 3}, nil),
		test.BuildArray(t, []int64{1, 2, 3}, nil),
	}

	setup := setupTestRowIterator(
		t,
		schema,
		arrays,
		[]string{"loss"},
		WithHistoryPageRange(HistoryPageParams{MinStep: 0, MaxStep: 2}),
	)
	defer setup.cleanup()

	if next, err := setup.iterator.Next(); err != nil {
		t.Fatal(err)
	} else if !next {
		t.Fatal("missing record")
	}
	assert.Equal(t, KVMapList{{Key: "loss", Value: int64(1)}}, setup.iterator.Value())

	if next, err := setup.iterator.Next(); err != nil {
		t.Fatal(err)
	} else if next {
		t.Fatalf("got unexpected record: %v", setup.iterator.Value())
	}
}

func TestRowIteratorUserMetricsWithTimestamp(t *testing.T) {
	t.Parallel()

	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Float64},
			{Name: "loss", Type: arrow.PrimitiveTypes.Int64},
			{Name: "_timestamp", Type: arrow.PrimitiveTypes.Float64},
		},
		nil,
	)
	arrays := []arrow.Array{
		test.BuildArray(t, []float64{1.0, 2.0, 3.0}, nil),
		test.BuildArray(t, []int64{1, 2, 3}, nil),
		test.BuildArray(t, []float64{1.0, 2.0, 3.0}, nil),
	}
	setup := setupTestRowIterator(
		t,
		schema,
		arrays,
		[]string{"loss", "_timestamp"},
		WithHistoryPageRange(HistoryPageParams{MinStep: 0, MaxStep: 2}),
	)
	defer setup.cleanup()

	if next, err := setup.iterator.Next(); err != nil {
		t.Fatal(err)
	} else if !next {
		t.Fatal("missing record")
	}
	assert.Equal(
		t,
		KVMapList{{Key: "loss", Value: int64(1)}, {Key: "_timestamp", Value: float64(1)}},
		setup.iterator.Value(),
	)

	if next, err := setup.iterator.Next(); err != nil {
		t.Fatal(err)
	} else if next {
		t.Fatalf("got unexpected record: %v", setup.iterator.Value())
	}
}

func TestRowIteratorUserMetricsWithTimestampReordered(t *testing.T) {
	t.Parallel()

	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_timestamp", Type: arrow.PrimitiveTypes.Float64},
			{Name: "loss", Type: arrow.PrimitiveTypes.Int64},
			{Name: "_step", Type: arrow.PrimitiveTypes.Float64},
		},
		nil,
	)
	arrays := []arrow.Array{
		test.BuildArray(t, []float64{1.0, 2.0, 3.0}, nil),
		test.BuildArray(t, []int64{1, 2, 3}, nil),
		test.BuildArray(t, []float64{1.0, 2.0, 3.0}, nil),
	}

	setup := setupTestRowIterator(
		t,
		schema,
		arrays,
		[]string{"loss", "_timestamp"},
		WithHistoryPageRange(HistoryPageParams{MinStep: 0, MaxStep: 2}),
	)
	defer setup.cleanup()

	if next, err := setup.iterator.Next(); err != nil {
		t.Fatal(err)
	} else if !next {
		t.Fatal("missing record")
	}
	assert.Equal(
		t,
		KVMapList{
			{Key: "_timestamp", Value: float64(1)},
			{Key: "loss", Value: int64(1)},
		},
		setup.iterator.Value(),
	)

	if next, err := setup.iterator.Next(); err != nil {
		t.Fatal(err)
	} else if next {
		t.Fatalf("got unexpected record: %v", setup.iterator.Value())
	}
}

func TestRowIteratorSystemMetrics(t *testing.T) {
	t.Parallel()

	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_timestamp", Type: arrow.PrimitiveTypes.Float64},
			{Name: "loss", Type: arrow.PrimitiveTypes.Int64},
			{Name: "_step", Type: arrow.PrimitiveTypes.Float64},
		},
		nil,
	)
	arrays := []arrow.Array{
		test.BuildArray(t, []float64{1.0, 2.0, 3.0, 4.0, 5.0}, nil),
		test.BuildArray(t, []int64{1, 2, 3, 4, 5}, nil),
		test.BuildArray(t, []float64{1.0, 2.0, 3.0, 4.0, 5.0}, nil),
	}

	setup := setupTestRowIterator(
		t,
		schema,
		arrays,
		[]string{"loss"},
		WithEventsPageRange(EventsPageParams{MinTimestamp: 1.0, MaxTimestamp: 4.0}),
	)

	if next, err := setup.iterator.Next(); err != nil {
		t.Fatal(err)
	} else if !next {
		t.Fatal("missing record")
	}
	assert.Equal(t, KVMapList{{Key: "loss", Value: int64(1)}}, setup.iterator.Value())

	if next, err := setup.iterator.Next(); err != nil {
		t.Fatal(err)
	} else if !next {
		t.Fatal("missing record")
	}
	assert.Equal(t, KVMapList{{Key: "loss", Value: int64(2)}}, setup.iterator.Value())

	if next, err := setup.iterator.Next(); err != nil {
		t.Fatal(err)
	} else if !next {
		t.Fatal("missing record")
	}
	assert.Equal(t, KVMapList{{Key: "loss", Value: int64(3)}}, setup.iterator.Value())

	if next, err := setup.iterator.Next(); err != nil {
		t.Fatal(err)
	} else if next {
		t.Fatalf("got unexpected record: %v", setup.iterator.Value())
	}
}

func TestTableIteratorWithNoColumnFilter(t *testing.T) {
	t.Parallel()
	schema := arrow.NewSchema([]arrow.Field{
		{
			Name: "_step",
			Type: &arrow.Int64Type{},
		},
		{
			Name:     "acc",
			Type:     &arrow.Float64Type{},
			Nullable: true,
		},
	}, nil)

	builder := array.NewRecordBuilder(memory.DefaultAllocator, schema)
	defer builder.Release()
	builder.Field(0).(*array.Int64Builder).AppendValues([]int64{0, 1}, nil)
	builder.Field(1).(*array.Float64Builder).AppendValues(
		[]float64{1, math.NaN()},
		[]bool{true, false},
	)
	record := builder.NewRecord()
	defer record.Release()

	reader, err := NewRecordIterator(record)
	if err != nil {
		t.Fatal(err)
	}
	var actual []interface{}
	next, err := reader.Next()
	for ; next && err == nil; next, err = reader.Next() {
		for _, kv := range reader.Value() {
			if kv.Key == "acc" {
				actual = append(actual, kv.Value)
				break
			}
		}
	}
	assert.Equal(t, []interface{}{float64(1), nil}, actual)
}

func TestTableIteratorFiltersRowsWithEmptyColumns(t *testing.T) {
	t.Parallel()
	schema := arrow.NewSchema([]arrow.Field{
		{
			Name: "_step",
			Type: &arrow.Int64Type{},
		},
		{
			Name:     "acc",
			Type:     &arrow.Float64Type{},
			Nullable: true,
		},
	}, nil)
	builder := array.NewRecordBuilder(memory.DefaultAllocator, schema)
	defer builder.Release()
	builder.Field(0).(*array.Int64Builder).AppendValues([]int64{0, 1}, nil)
	builder.Field(1).(*array.Float64Builder).AppendValues(
		[]float64{1, math.NaN()},
		[]bool{true, false},
	)
	record := builder.NewRecordBatch()
	defer record.Release()

	reader, err := NewRecordIterator(
		record,
		RecordIteratorWithResultCols([]string{"_step", "acc"}),
	)
	require.NoError(t, err)

	next, err := reader.Next()
	assert.NoError(t, err)
	assert.True(t, next)

	next, err = reader.Next()
	assert.NoError(t, err)
	assert.False(t, next)
}

func TestTableIteratorFiltersRowsWithStepOutOfRange(t *testing.T) {
	t.Parallel()
	schema := arrow.NewSchema([]arrow.Field{
		{
			Name: "_step",
			Type: &arrow.Int64Type{},
		},
	}, nil)
	builder := array.NewRecordBuilder(memory.DefaultAllocator, schema)
	defer builder.Release()
	builder.Field(0).(*array.Int64Builder).AppendValues([]int64{0, 1, 2}, nil)
	record := builder.NewRecord()
	defer record.Release()

	reader, err := NewRecordIterator(
		record,
		RecordIteratorWithPage(IteratorConfig{
			Key: StepKey,
			Min: 1,
			Max: 2,
		}),
	)
	if err != nil {
		t.Fatal(err)
	}
	if next, err := reader.Next(); err != nil {
		t.Fatal(err)
	} else if !next {
		t.Fatal("missing record")
	} else if value := reader.Value()[0]; value.Key != "_step" || value.Value != int64(1) {
		t.Fatalf("go unexpected record: %v", value)
	}

	if next, err := reader.Next(); err != nil {
		t.Fatal(err)
	} else if next {
		t.Fatalf("got unexpected record: %v", reader.Value())
	}
}

func TestTableIteratorMemoryLeak(t *testing.T) {
	t.Parallel()
	allocator := memory.NewCheckedAllocator(memory.DefaultAllocator)
	schema := arrow.NewSchema([]arrow.Field{
		{
			Name: "_step",
			Type: &arrow.Int64Type{},
		},
	}, nil)
	builder := array.NewRecordBuilder(allocator, schema)
	defer builder.Release()
	builder.Field(0).(*array.Int64Builder).AppendValues([]int64{0, 1, 2}, nil)
	record := builder.NewRecord()
	defer record.Release()

	reader, err := NewRecordIterator(record)
	if err != nil {
		t.Fatal(err)
	}
	record.Release()

	steps := []int64{}
	next, err := reader.Next()
	for ; next && err == nil; next, err = reader.Next() {
		steps = append(steps, reader.Value()[0].Value.(int64))
	}
	if err != nil {
		t.Fatal(err)
	}
	assert.Equal(t, steps, []int64{0, 1, 2})

	reader.Release()
	allocator.AssertSize(t, 0)
}

func TestRowGroupIteratorMemoryLeak(t *testing.T) {
	t.Parallel()
	allocator := memory.NewCheckedAllocator(memory.DefaultAllocator)
	defer allocator.AssertSize(t, 0)

	filePath := "../../../../tests/files/history.parquet"
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

	r, err := pqarrow.NewFileReader(pf, pqarrow.ArrowReadProperties{}, allocator)
	if err != nil {
		t.Fatal(err)
	}

	// all row groups should be read
	ctx := context.Background()
	page := HistoryPageParams{
		MinStep: 0,
		MaxStep: 999,
	}
	it, err := NewRowIterator(
		ctx,
		r,
		[]string{"_step"},
		WithHistoryPageRange(page),
	)
	if err != nil {
		t.Fatal(err)
	}
	defer it.Release()

	steps := []float64{}
	next, err := it.Next()
	for ; next && err == nil; next, err = it.Next() {
		steps = append(steps, it.Value()[0].Value.(float64))
	}
	if err != nil {
		t.Fatal(err)
	}

	expected := make([]float64, 999)
	for i := range expected {
		expected[i] = float64(i)
	}
	assert.Equal(t, steps, expected)

	if err := pf.Close(); err != nil {
		t.Fatal(err)
	}

	it.Release()
	allocator.AssertSize(t, 0)
}

func TestRowGroupIteratorWithListOfStructs(t *testing.T) {
	t.Parallel()
	schema := arrow.NewSchema([]arrow.Field{
		{
			Nullable: true,
			Name:     "outer",
			Type: arrow.ListOf(
				arrow.StructOf(arrow.Field{
					Nullable: true,
					Name:     "nested",
					Type:     arrow.PrimitiveTypes.Int64,
				}),
			),
		},
	}, nil)
	data := []map[string]any{
		{"outer": nil},
		{"outer": []any{map[string]any{"nested": int64(1)}}},
		{"outer": []any{map[string]any{"nested": int64(2)}}},
		{"outer": []any{map[string]any{"nested": int64(3)}}},
		{"outer": []any{map[string]any{"nested": int64(4)}}},
		{"outer": []any{map[string]any{"nested": int64(5)}}},
		{"outer": []any{map[string]any{"nested": int64(6)}}},
		{"outer": []any{map[string]any{"nested": int64(7)}}},
		{"outer": []any{map[string]any{"nested": int64(8)}}},
	}

	tempFile := filepath.Join(t.TempDir(), "test_list_of_structs.parquet")
	test.CreateTestParquetFileFromData(t, tempFile, schema, data)
	pr, err := file.OpenParquetFile(tempFile, true)
	require.NoError(t, err)
	defer pr.Close()

	r, err := pqarrow.NewFileReader(pr, pqarrow.ArrowReadProperties{}, memory.DefaultAllocator)
	require.NoError(t, err)

	it, err := NewRowIterator(
		context.Background(),
		r,
		[]string{},
		WithHistoryPageRange(HistoryPageParams{
			MinStep: 0,
			MaxStep: math.MaxInt64,
		}),
	)
	require.NoError(t, err)
	defer it.Release()

	// Iterate through all rows and verify values match the input data
	for i, row := range data {
		expected := row["outer"]
		next, err := it.Next()
		require.NoError(t, err, "Error getting row %d", i)
		require.True(t, next, "Expected row %d to exist", i)

		// Since we're getting all columns, extract just the outer value
		var actual any
		for _, kv := range it.Value() {
			if kv.Key == "outer" {
				actual = kv.Value
				break
			}
		}

		if expected == nil {
			assert.Nil(t, actual, "Row %d: expected outer to be nil", i)
		} else {
			assert.Equal(t, expected, actual, "Row %d: outer value mismatch", i)
		}
	}

	// Verify no more rows beyond what's in the data
	next, err := it.Next()
	require.NoError(t, err)
	require.False(t, next, "Expected no more rows after %d rows", len(data))
}

func TestRowGroupIteratorWithListOfNestedStructs(t *testing.T) {
	t.Parallel()
	schema := arrow.NewSchema(
		[]arrow.Field{
			{
				Nullable: true,
				Name:     "BoundingBoxDebugger",
				Type: arrow.StructOf(
					arrow.Field{
						Nullable: true,
						Name:     "all_boxes",
						Type: arrow.ListOf(arrow.StructOf(
							arrow.Field{
								Nullable: true,
								Name:     "predictions",
								Type: arrow.StructOf(
									arrow.Field{
										Nullable: true,
										Name:     "path",
										Type:     arrow.BinaryTypes.String,
									},
								),
							},
						)),
					},
				),
			},
		},
		nil,
	)
	data := []map[string]any{
		{"BoundingBoxDebugger": nil},
		{"BoundingBoxDebugger": map[string]any{
			"all_boxes": []any{
				map[string]any{"predictions": map[string]any{"path": "hello"}},
				map[string]any{"predictions": map[string]any{"path": "hello"}},
				map[string]any{"predictions": map[string]any{"path": "hello"}},
				map[string]any{"predictions": map[string]any{"path": "hello"}},
				map[string]any{"predictions": map[string]any{"path": "hello"}},
				map[string]any{"predictions": map[string]any{"path": "hello"}},
			},
		}},
		{"BoundingBoxDebugger": nil},
	}
	tempFile := filepath.Join(t.TempDir(), "test_list_of_structs.parquet")
	test.CreateTestParquetFileFromData(t, tempFile, schema, data)
	pr, err := file.OpenParquetFile(tempFile, true)
	require.NoError(t, err)
	defer pr.Close()

	r, err := pqarrow.NewFileReader(pr, pqarrow.ArrowReadProperties{}, memory.DefaultAllocator)
	require.NoError(t, err)

	it, err := NewRowIterator(
		context.Background(),
		r,
		[]string{},
		WithHistoryPageRange(HistoryPageParams{
			MinStep: 0,
			MaxStep: math.MaxInt64,
		}),
	)
	require.NoError(t, err)
	defer it.Release()

	// Iterate through all rows and verify values match the input data
	for i, row := range data {
		expected := row["outer"]
		next, err := it.Next()
		require.NoError(t, err, "Error getting row %d", i)
		require.True(t, next, "Expected row %d to exist", i)

		// Since we're getting all columns, extract just the outer value
		var actual any
		for _, kv := range it.Value() {
			if kv.Key == "outer" {
				actual = kv.Value
				break
			}
		}

		if expected == nil {
			assert.Nil(t, actual, "Row %d: expected outer to be nil", i)
		} else {
			assert.Equal(t, expected, actual, "Row %d: outer value mismatch", i)
		}
	}

	// Verify no more rows beyond what's in the data
	next, err := it.Next()
	require.NoError(t, err)
	require.False(t, next, "Expected no more rows after %d rows", len(data))
}

func TestEmptyFile(t *testing.T) {
	t.Parallel()
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
	page := HistoryPageParams{
		MinStep: 0,
		MaxStep: 999,
		Samples: 10,
	}
	it, err := NewRowIterator(ctx, r, []string{"_step"}, WithHistoryPageRange(page))
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

func TestRowIteratorWithMissingColumns(t *testing.T) {
	t.Parallel()
	schema := arrow.NewSchema([]arrow.Field{
		{Name: "_step", Type: arrow.PrimitiveTypes.Float64},
		{Name: "loss", Type: arrow.PrimitiveTypes.Int64},
	}, nil)
	arrays := []arrow.Array{
		test.BuildArray(t, []float64{1.0, 2.0}, nil),
		test.BuildArray(t, []int64{1, 2}, nil),
	}

	setup := setupTestRowIterator(
		t,
		schema,
		arrays,
		[]string{"_step", "loss", "nonexistent_column"},
		WithHistoryPageRange(HistoryPageParams{MinStep: 0, MaxStep: 2}),
	)

	// Should get a dummy iterator that returns no rows
	if next, err := setup.iterator.Next(); err != nil {
		t.Fatal(err)
	} else if next {
		t.Fatal("expected no rows from iterator")
	}
}

func TestRowIteratorWithComplexColumns(t *testing.T) {
	t.Parallel()

	schema := arrow.NewSchema([]arrow.Field{
		{Name: "_step", Type: arrow.PrimitiveTypes.Float64},
		{Name: "loss", Type: arrow.PrimitiveTypes.Int64},
		{Name: "nested", Type: arrow.StructOf(
			arrow.Field{Name: "nested_a", Type: arrow.PrimitiveTypes.Float64},
			arrow.Field{Name: "nested_b", Type: arrow.PrimitiveTypes.Float64},
		)},
	}, nil)
	data := []map[string]any{
		{"_step": 1.0, "loss": int64(1), "nested": map[string]any{"nested_a": 1.0, "nested_b": 2.0}},
		{"_step": 2.0, "loss": int64(2), "nested": map[string]any{"nested_a": 2.0, "nested_b": 4.0}},
		{"_step": 3.0, "loss": int64(3), "nested": map[string]any{"nested_a": 4.0, "nested_b": 6.0}},
	}
	tempFile := filepath.Join(t.TempDir(), "test_list_of_structs.parquet")
	test.CreateTestParquetFileFromData(t, tempFile, schema, data)
	pr, err := file.OpenParquetFile(tempFile, true)
	require.NoError(t, err)
	defer pr.Close()

	r, err := pqarrow.NewFileReader(pr, pqarrow.ArrowReadProperties{}, memory.DefaultAllocator)
	require.NoError(t, err)

	it, err := NewRowIterator(
		context.Background(),
		r,
		[]string{},
		WithHistoryPageRange(HistoryPageParams{
			MinStep: 0,
			MaxStep: math.MaxInt64,
		}),
	)
	require.NoError(t, err)
	defer it.Release()

	// Verify first row
	if next, err := it.Next(); err != nil {
		t.Fatal(err)
	} else if !next {
		t.Fatal("missing first record")
	}

	expectedFirstRow := KVMapList{
		{Key: "_step", Value: 1.0},
		{Key: "loss", Value: int64(1)},
		{Key: "nested", Value: map[string]any{
			"nested_a": 1.0,
			"nested_b": 2.0,
		}},
	}
	assert.Equal(t, it.Value(), expectedFirstRow)

	// Verify second row
	if next, err := it.Next(); err != nil {
		t.Fatal(err)
	} else if !next {
		t.Fatal("missing second record")
	}

	expectedSecondRow := KVMapList{
		{Key: "_step", Value: 2.0},
		{Key: "loss", Value: int64(2)},
		{Key: "nested", Value: map[string]any{
			"nested_a": 2.0,
			"nested_b": 4.0,
		}},
	}
	assert.Equal(t, it.Value(), expectedSecondRow)

	// Verify third row
	if next, err := it.Next(); err != nil {
		t.Fatal(err)
	} else if !next {
		t.Fatal("missing third record")
	}

	expectedThirdRow := KVMapList{
		{Key: "_step", Value: 3.0},
		{Key: "loss", Value: int64(3)},
		{Key: "nested", Value: map[string]any{
			"nested_a": 4.0,
			"nested_b": 6.0,
		}},
	}
	assert.Equal(t, it.Value(), expectedThirdRow)
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
			name:        "select all columns when empty list",
			columns:     []string{},
			wantIndices: []int{0, 1, 2, 3},
			wantErr:     false,
		},
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
			indices, err := selectColumns(s, tt.columns)
			if tt.wantErr {
				assert.Error(t, err)
			} else {
				assert.NoError(t, err)
				assert.Equal(t, tt.wantIndices, indices)
			}
		})
	}
}

func TestIteratorConfig_Applies_Changes(t *testing.T) {
	t.Run("WithHistoryPageRange", func(t *testing.T) {
		config := IteratorConfig{}
		page := HistoryPageParams{
			MinStep: 10,
			MaxStep: 100,
		}
		config.Apply(WithHistoryPageRange(page))

		assert.Equal(t, StepKey, config.Key)
		assert.Equal(t, float64(10), config.Min)
		assert.Equal(t, float64(100), config.Max)
	})

	t.Run("WithEventsPageRange", func(t *testing.T) {
		config := IteratorConfig{}
		page := EventsPageParams{
			MinTimestamp: 1000.5,
			MaxTimestamp: 2000.5,
		}
		config.Apply(WithEventsPageRange(page))

		assert.Equal(t, TimestampKey, config.Key)
		assert.Equal(t, 1000.5, config.Min)
		assert.Equal(t, 2000.5, config.Max)
	})
}

func TestRecordIteratorWithEmptyRecord(t *testing.T) {
	pool := memory.NewGoAllocator()

	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
		},
		nil,
	)

	builder := array.NewRecordBuilder(pool, schema)
	defer builder.Release()

	// Create empty record
	record := builder.NewRecordBatch()
	defer record.Release()

	iter, err := NewRecordIterator(record)
	require.NoError(t, err)
	defer iter.Release()

	hasNext, err := iter.Next()
	assert.NoError(t, err)
	assert.False(t, hasNext)
}
