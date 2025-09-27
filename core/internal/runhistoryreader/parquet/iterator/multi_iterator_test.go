package iterator

import (
	"path/filepath"
	"testing"

	"github.com/apache/arrow-go/v18/arrow"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	test "github.com/wandb/wandb/core/tests/parquet"
)

type testIterator struct {
	value   KeyValueList
	hasNext bool
}

func (t *testIterator) Next() (bool, error) {
	if t.hasNext {
		t.hasNext = false
		return true, nil
	}
	return false, nil
}

func (t *testIterator) Value() KeyValueList {
	return t.value
}

func (t *testIterator) Release() {}

func TestMultiIterator(t *testing.T) {
	iterValues := []KeyValueList{
		{{Key: "a", Value: 1}},
		{{Key: "b", Value: 2}},
	}
	iterators := []RowIterator{
		&testIterator{value: iterValues[0], hasNext: true},
		&testIterator{value: iterValues[1], hasNext: true},
	}

	mIter := NewMultiIterator(iterators)

	for _, value := range iterValues {
		hasNext, err := mIter.Next()
		assert.NoError(t, err)
		assert.True(t, hasNext)
		assert.Equal(t, value, mIter.Value())
	}

	hasNext, err := mIter.Next()
	assert.NoError(t, err)
	assert.False(t, hasNext)
}

func TestMultiIterator_ReadsAllRows(t *testing.T) {
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			{Name: "value", Type: arrow.PrimitiveTypes.Float64},
		},
		nil,
	)
	dataPart1 := []map[string]any{
		{"_step": int64(0), "value": 0.0},
		{"_step": int64(10), "value": 10.0},
		{"_step": int64(20), "value": 20.0},
	}
	dataPart2 := []map[string]any{
		{"_step": int64(30), "value": 30.0},
		{"_step": int64(40), "value": 40.0},
		{"_step": int64(50), "value": 50.0},
	}
	tempFile1 := filepath.Join(t.TempDir(), "test1.parquet")
	tempFile2 := filepath.Join(t.TempDir(), "test2.parquet")
	test.CreateTestParquetFileFromData(t, tempFile1, schema, dataPart1)
	test.CreateTestParquetFileFromData(t, tempFile2, schema, dataPart2)
	it1, cleanup1 := getRowIteratorForFile(
		t,
		tempFile1,
		[]string{"_step", "value"},
		nil,
	)
	it2, cleanup2 := getRowIteratorForFile(
		t,
		tempFile2,
		[]string{"_step", "value"},
		nil,
	)
	defer cleanup1()
	defer cleanup2()

	multiReader := NewMultiIterator([]RowIterator{it1, it2})

	// Verify all rows are read
	values := make([]map[string]any, 0)
	next, err := multiReader.Next()
	assert.NoError(t, err)
	for next {
		value := multiReader.Value()
		values = append(values, map[string]any{
			"_step": value[0].Value,
			"value": value[1].Value,
		})
		next, err = multiReader.Next()
		assert.NoError(t, err)
	}
	expectedValues := append([]map[string]any{}, dataPart1...)
	expectedValues = append(expectedValues, dataPart2...)
	assert.Equal(t, len(expectedValues), len(values))
	assert.Equal(t, expectedValues, values)
}

func TestMultiIterator_WithPageRange_AcrossPartitions(t *testing.T) {
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			{Name: "value", Type: arrow.PrimitiveTypes.Float64},
		},
		nil,
	)
	dataPart1 := []map[string]any{
		{"_step": int64(0), "value": 0.0},
		{"_step": int64(10), "value": 10.0},
		{"_step": int64(20), "value": 20.0},
	}
	dataPart2 := []map[string]any{
		{"_step": int64(30), "value": 30.0},
		{"_step": int64(40), "value": 40.0},
		{"_step": int64(50), "value": 50.0},
	}
	tempFile1 := filepath.Join(t.TempDir(), "test1.parquet")
	tempFile2 := filepath.Join(t.TempDir(), "test2.parquet")
	test.CreateTestParquetFileFromData(t, tempFile1, schema, dataPart1)
	test.CreateTestParquetFileFromData(t, tempFile2, schema, dataPart2)
	pageOpt := WithHistoryPageRange(HistoryPageParams{
		MinStep: 10,
		MaxStep: 40,
	})
	it1, cleanup1 := getRowIteratorForFile(
		t,
		tempFile1,
		[]string{"_step", "value"},
		pageOpt,
	)
	it2, cleanup2 := getRowIteratorForFile(
		t,
		tempFile2,
		[]string{"_step", "value"},
		pageOpt,
	)
	defer cleanup1()
	defer cleanup2()
	multiReader := NewMultiIterator(
		[]RowIterator{it1, it2},
	)

	// Read all rows and verify they're within the range
	values := make([]map[string]any, 0)
	next, err := multiReader.Next()
	assert.NoError(t, err)
	for next {
		value := multiReader.Value()
		values = append(values, map[string]any{
			"_step": value[0].Value,
			"value": value[1].Value,
		})
		next, err = multiReader.Next()
		require.NoError(t, err)
	}

	expectedValues := []map[string]any{
		{"_step": int64(10), "value": 10.0},
		{"_step": int64(20), "value": 20.0},
		{"_step": int64(30), "value": 30.0},
	}
	assert.Equal(t, len(expectedValues), len(values))
	assert.Equal(t, expectedValues, values)
}
