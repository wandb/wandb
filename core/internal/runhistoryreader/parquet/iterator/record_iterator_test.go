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

	reader, err := NewRecordIterator(
		record,
		RecordIteratorWithResultCols([]string{"_step", "acc"}),
	)
	require.NoError(t, err)

	next, err := reader.Next()
	assert.NoError(t, err)
	assert.True(t, next)
	assert.Equal(
		t,
		KeyValueList{
			{Key: "_step", Value: int64(0)},
			{Key: "acc", Value: float64(1)},
		},
		reader.Value(),
	)

	// Verify no more data returned
	next, err = reader.Next()
	assert.NoError(t, err)
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

	reader, err := NewRecordIterator(
		record,
		RecordIteratorWithPage(IteratorConfig{
			Key: StepKey,
			Min: 1,
			Max: 2,
		}),
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
	assert.NoError(t, err)
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

	reader, err := NewRecordIterator(record)
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

	iter, err := NewRecordIterator(record)
	require.NoError(t, err)
	defer iter.Release()

	hasNext, err := iter.Next()
	assert.NoError(t, err)
	assert.False(t, hasNext)
	assert.Nil(t, iter.Value()[0].Value)
}
