package iterator

import (
	"math"
	"testing"

	"github.com/apache/arrow-go/v18/arrow"
	"github.com/apache/arrow-go/v18/arrow/array"
	"github.com/apache/arrow-go/v18/arrow/memory"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestRecordIterator_ErrorsOnMissingColumns(t *testing.T) {
	schema := arrow.NewSchema([]arrow.Field{
		{
			Name: "_step",
			Type: &arrow.Int64Type{},
		},
	}, nil)
	builder := array.NewRecordBuilder(memory.DefaultAllocator, schema)
	defer builder.Release()
	builder.Field(0).(*array.Int64Builder).AppendValues([]int64{0, 1}, nil)
	record := builder.NewRecordBatch()
	defer record.Release()

	_, err := NewRowGroupIterator(
		record,
		&SelectedColumns{
			requestedColumns: map[string]struct{}{"_step": {}, "acc": {}},
			selectAll:        false,
		},
		&SelectedRowsRange{
			indexKey: StepKey,
			minValue: 0,
			maxValue: 1,
		},
	)

	require.Error(t, err)
	require.ErrorContains(t, err, "column acc not found in record batch")
}

func TestRecordIterator_ErrorsOnMissingIndexKey(t *testing.T) {
	schema := arrow.NewSchema([]arrow.Field{
		{
			Name: "acc",
			Type: &arrow.Int64Type{},
		},
	}, nil)
	builder := array.NewRecordBuilder(memory.DefaultAllocator, schema)
	defer builder.Release()
	builder.Field(0).(*array.Int64Builder).AppendValues([]int64{0, 1}, nil)
	record := builder.NewRecordBatch()
	defer record.Release()

	_, err := NewRowGroupIterator(
		record,
		&SelectedColumns{
			requestedColumns: map[string]struct{}{"acc": {}},
			selectAll:        false,
		},
		&SelectedRowsRange{
			indexKey: StepKey,
			minValue: 0,
			maxValue: 1,
		},
	)

	require.Error(t, err)
	require.ErrorContains(t, err, "column _step not found in record batch")
}

func TestRecordIterator_FiltersRowsWithEmptyColumns(t *testing.T) {
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

	reader, err := NewRowGroupIterator(
		record,
		&SelectedColumns{
			requestedColumns: map[string]struct{}{"_step": {}, "acc": {}},
			selectAll:        false,
		},
		&SelectedRowsRange{
			indexKey: StepKey,
			minValue: 0,
			maxValue: 1,
		},
	)
	require.NoError(t, err)

	next, err := reader.Next()
	assert.NoError(t, err)
	assert.True(t, next)
	expectedValue := map[string]any{
		"_step": int64(0),
		"acc":   float64(1),
	}
	for _, kvPair := range reader.Value() {
		assert.Equal(t, expectedValue[kvPair.Key], kvPair.Value)
	}

	// Verify no more data returned
	next, err = reader.Next()
	assert.ErrorIs(t, err, ErrRowExceedsMaxValue)
	assert.False(t, next, "Expected no more data returned")
}

func TestRecordIterator_FiltersRowsWithStepOutOfRange(t *testing.T) {
	schema := arrow.NewSchema([]arrow.Field{
		{
			Name: "_step",
			Type: &arrow.Int64Type{},
		},
	}, nil)
	builder := array.NewRecordBuilder(memory.DefaultAllocator, schema)
	defer builder.Release()
	builder.Field(0).(*array.Int64Builder).AppendValues([]int64{0, 1, 2}, nil)
	record := builder.NewRecordBatch()
	defer record.Release()

	reader, err := NewRowGroupIterator(
		record,
		&SelectedColumns{
			requestedColumns: map[string]struct{}{"_step": {}},
			selectAll:        false,
		},
		&SelectedRowsRange{
			indexKey: StepKey,
			minValue: 1,
			maxValue: 2,
		},
	)
	require.NoError(t, err)

	next, err := reader.Next()
	assert.NoError(t, err)
	assert.True(t, next)
	assert.Equal(
		t,
		KeyValueList{{Key: "_step", Value: int64(1)}},
		reader.Value(),
	)

	// Verify no more data returned
	next, err = reader.Next()
	assert.ErrorIs(t, err, ErrRowExceedsMaxValue)
	assert.False(t, next, "Expected no more data returned")
}

func TestRecordIterator_ReleaseFreesMemory(t *testing.T) {
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
	record := builder.NewRecordBatch()
	defer record.Release()

	reader, err := NewRowGroupIterator(
		record,
		&SelectedColumns{
			requestedColumns: map[string]struct{}{"_step": {}},
			selectAll:        false,
		},
		&SelectedRowsRange{
			indexKey: StepKey,
			minValue: 0,
			maxValue: 3,
		},
	)
	if err != nil {
		t.Fatal(err)
	}
	record.Release()

	for i := range 3 {
		next, err := reader.Next()
		assert.NoError(t, err)
		assert.True(t, next)
		assert.Equal(t, KeyValueList{{Key: "_step", Value: int64(i)}}, reader.Value())
	}

	// Verify no more data returned
	next, err := reader.Next()
	assert.NoError(t, err)
	assert.False(t, next, "Expected no more data returned")

	reader.Release()
	allocator.AssertSize(t, 0)
}

func TestRecordIterator_WithEmptyRecordIsNil(t *testing.T) {
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
		},
		nil,
	)
	builder := array.NewRecordBuilder(memory.DefaultAllocator, schema)
	defer builder.Release()
	record := builder.NewRecordBatch()
	defer record.Release()

	iter, err := NewRowGroupIterator(
		record,
		&SelectedColumns{
			requestedColumns: map[string]struct{}{"_step": {}},
			selectAll:        false,
		},
		&SelectedRowsRange{
			indexKey: StepKey,
			minValue: 0,
			maxValue: 0,
		},
	)
	require.NoError(t, err)
	defer iter.Release()

	hasNext, err := iter.Next()
	assert.NoError(t, err)
	assert.False(t, hasNext)
	assert.Nil(t, iter.Value()[0].Value)
}
