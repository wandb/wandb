package iterator

import (
	"path/filepath"
	"testing"

	"github.com/apache/arrow-go/v18/arrow"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/iterator/iteratortest"
)

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
	iteratortest.CreateTestParquetFileFromData(t, tempFile1, schema, dataPart1)
	iteratortest.CreateTestParquetFileFromData(t, tempFile2, schema, dataPart2)
	it1 := getRowIteratorForFile(
		t,
		tempFile1,
		[]string{"_step", "value"},
		StepKey,
		0,
		1000,
	)
	it2 := getRowIteratorForFile(
		t,
		tempFile2,
		[]string{"_step", "value"},
		StepKey,
		0,
		1000,
	)

	multiReader := NewMultiIterator([]*ParquetDataIterator{it1, it2})

	// Verify all rows are read
	actualValues := make([]map[string]any, 0)
	next, err := multiReader.Next()
	assert.NoError(t, err)
	for next {
		v := multiReader.Value()
		values := make(map[string]any)

		for _, v := range v {
			values[v.Key] = v.Value
		}

		actualValues = append(actualValues, values)
		next, err = multiReader.Next()
		require.NoError(t, err)
	}
	expectedValues := append([]map[string]any{}, dataPart1...)
	expectedValues = append(expectedValues, dataPart2...)
	assert.Equal(t, len(expectedValues), len(actualValues))
	for _, value := range actualValues {
		assert.Contains(t, expectedValues, value)
	}
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
	iteratortest.CreateTestParquetFileFromData(t, tempFile1, schema, dataPart1)
	iteratortest.CreateTestParquetFileFromData(t, tempFile2, schema, dataPart2)
	it1 := getRowIteratorForFile(
		t,
		tempFile1,
		[]string{"_step", "value"},
		StepKey,
		10,
		40,
	)
	it2 := getRowIteratorForFile(
		t,
		tempFile2,
		[]string{"_step", "value"},
		StepKey,
		10,
		40,
	)
	multiReader := NewMultiIterator([]*ParquetDataIterator{it1, it2})

	// Read all rows and verify they're within the range
	actualValues := make([]map[string]any, 0)
	next, err := multiReader.Next()
	assert.NoError(t, err)
	for next {
		v := multiReader.Value()
		values := make(map[string]any)

		for _, v := range v {
			values[v.Key] = v.Value
		}

		actualValues = append(actualValues, values)
		next, _ = multiReader.Next()
	}

	expectedValues := []map[string]any{
		{"_step": int64(10), "value": 10.0},
		{"_step": int64(20), "value": 20.0},
		{"_step": int64(30), "value": 30.0},
	}

	for _, value := range actualValues {
		assert.Contains(t, expectedValues, value)
	}
}
