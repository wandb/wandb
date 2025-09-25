package parquet

import (
	"bytes"
	"context"
	"encoding/binary"
	"math"
	"path/filepath"
	"testing"

	"github.com/apache/arrow-go/v18/arrow"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	test "github.com/wandb/wandb/core/tests/parquet"
)

func TestNewParquetPartitionReader(t *testing.T) {
	schema := arrow.NewSchema(
		[]arrow.Field{{Name: "_step", Type: arrow.PrimitiveTypes.Int64}},
		nil,
	)
	data := []map[string]any{{"_step": 0}}
	historyFilePath := filepath.Join(t.TempDir(), "test.parquet")
	test.CreateTestParquetFileFromData(t, historyFilePath, schema, data)
	pf, err := LocalParquetFile(historyFilePath, true)
	require.NoError(t, err)

	reader := NewParquetPartitionReader(t.Context(), pf, []string{}, nil)

	assert.NotNil(t, reader)
	assert.NotNil(t, reader.ctx)
	assert.NotNil(t, reader.file)
	assert.NotNil(t, reader.dataReady)
	assert.NoError(t, reader.err)
}

func TestParquetPartitionReader_MetaData(t *testing.T) {
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			{Name: "metric", Type: arrow.PrimitiveTypes.Float64},
		},
		nil,
	)
	data := []map[string]any{
		{"_step": 0, "metric": 1.0},
		{"_step": 1, "metric": 2.0},
	}
	historyFilePath := filepath.Join(t.TempDir(), "test.parquet")
	test.CreateTestParquetFileFromData(t, historyFilePath, schema, data)

	pf, err := LocalParquetFile(historyFilePath, true)
	require.NoError(t, err)

	reader := NewParquetPartitionReader(t.Context(), pf, []string{"_step"}, nil)
	defer reader.Release()

	// Test metadata retrieval
	meta, err := reader.MetaData()
	assert.NoError(t, err)
	assert.NotNil(t, meta)
	assert.Equal(t, int64(2), meta.NumRows)
	assert.Equal(t, 2, meta.Schema.NumColumns())
	assert.Equal(t, "_step", meta.Schema.Column(0).Name())
	assert.Equal(t, "metric", meta.Schema.Column(1).Name())
}

// TestParquetPartitionReader_NextAndValue tests the Next and Value methods
func TestParquetPartitionReader_Iteration(t *testing.T) {
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			{Name: "loss", Type: arrow.PrimitiveTypes.Float64},
		},
		nil,
	)
	data := []map[string]any{
		{"_step": 0, "loss": 0.5},
		{"_step": 1, "loss": 0.4},
	}
	historyFilePath := filepath.Join(t.TempDir(), "test.parquet")
	test.CreateTestParquetFileFromData(t, historyFilePath, schema, data)
	pf, err := LocalParquetFile(historyFilePath, true)
	require.NoError(t, err)

	reader := NewParquetPartitionReader(t.Context(), pf, []string{}, nil)
	defer reader.Release()

	// Verify data read
	numRows := 0
	for {
		hasNext, err := reader.Next()
		require.NoError(t, err)
		if !hasNext {
			break
		}
		// rows = append(rows, reader.Value())
		assert.NotNil(t, reader.Value())
		value := reader.Value()
		assert.Equal(t, int64(numRows), value[0].Value)
		assert.Equal(t, 0.5-float64(numRows)*0.1, value[1].Value)
		numRows++
	}
	assert.Equal(t, 2, numRows)
}

func TestParquetPartitionReader_ValueIterator(t *testing.T) {
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			{Name: "value", Type: arrow.PrimitiveTypes.Float64},
		},
		nil,
	)
	data := []map[string]any{
		{"_step": 0, "value": 1.0},
		{"_step": 1, "value": 2.0},
		{"_step": 2, "value": 3.0},
	}
	historyFilePath := filepath.Join(t.TempDir(), "test.parquet")
	test.CreateTestParquetFileFromData(t, historyFilePath, schema, data)
	pf, err := LocalParquetFile(historyFilePath, true)
	require.NoError(t, err)

	reader := NewParquetPartitionReader(t.Context(), pf, []string{}, nil)
	defer reader.Release()

	// Verify data read
	count := 0
	var lastError error
	for value, err := range reader.All() {
		if err != nil {
			lastError = err
			break
		}
		assert.NotNil(t, value)
		assert.Equal(t, int64(count), value[0].Value)
		assert.Equal(t, float64(count+1), value[1].Value)
		count++
	}

	assert.NoError(t, lastError)
	assert.Equal(t, 3, count)
}

func TestParquetPartitionReader_Release(t *testing.T) {
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
		},
		nil,
	)
	data := []map[string]any{
		{"_step": 0},
	}
	historyFilePath := filepath.Join(t.TempDir(), "test_release.parquet")
	test.CreateTestParquetFileFromData(t, historyFilePath, schema, data)

	pf, err := LocalParquetFile(historyFilePath, true)
	require.NoError(t, err)

	ctx := context.Background()
	reader := NewParquetPartitionReader(ctx, pf, []string{"_step"}, nil)

	// Read first row successfully
	hasNext, err := reader.Next()
	require.NoError(t, err)
	assert.True(t, hasNext)

	assert.NotPanics(t, func() {
		reader.Release()
	})
}

func TestGetColumnRangeFromStats(t *testing.T) {
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			{Name: "float_metric", Type: arrow.PrimitiveTypes.Float64},
		},
		nil,
	)
	data := []map[string]any{
		{"_step": 10, "float_metric": 1.5},
		{"_step": 20, "float_metric": 2.5},
		{"_step": 30, "float_metric": 3.5},
		{"_step": 40, "float_metric": 4.5},
		{"_step": 50, "float_metric": 5.5},
	}
	historyFilePath := filepath.Join(t.TempDir(), "test_stats.parquet")
	test.CreateTestParquetFileFromData(t, historyFilePath, schema, data)
	pf, err := LocalParquetFile(historyFilePath, true)
	require.NoError(t, err)
	reader := NewParquetPartitionReader(t.Context(), pf, []string{}, nil)
	defer reader.Release()

	meta := pf.ParquetReader().MetaData()
	assert.NotNil(t, meta)

	minVal, maxVal, err := GetColumnRangeFromStats(meta, 0, "_step")
	assert.NoError(t, err)
	assert.Equal(t, float64(10), minVal)
	assert.Equal(t, float64(50), maxVal)

	minVal, maxVal, err = GetColumnRangeFromStats(meta, 0, "float_metric")
	require.NoError(t, err)
	assert.InDelta(t, 1.5, minVal, 0.001)
	assert.InDelta(t, 5.5, maxVal, 0.001)

	_, _, err = GetColumnRangeFromStats(meta, 999, "_step")
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "row group not found")

	_, _, err = GetColumnRangeFromStats(meta, 0, "nonexistent_column")
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "column not found")
}

func TestGetColumnRangeFromStats_UnsupportedType(t *testing.T) {
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "text_column", Type: arrow.BinaryTypes.String},
		},
		nil,
	)
	data := []map[string]any{
		{"text_column": "hello"},
		{"text_column": "world"},
	}
	historyFilePath := filepath.Join(t.TempDir(), "test.parquet")
	test.CreateTestParquetFileFromData(t, historyFilePath, schema, data)
	pf, err := LocalParquetFile(historyFilePath, true)
	require.NoError(t, err)

	reader := NewParquetPartitionReader(t.Context(), pf, []string{}, nil)
	defer reader.Release()

	meta := pf.ParquetReader().MetaData()
	assert.NotNil(t, meta)

	_, _, err = GetColumnRangeFromStats(meta, 0, "text_column")
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "unsupported type")
}

func TestDecodeValue(t *testing.T) {
	t.Run("DecodeInt64", func(t *testing.T) {
		expected := int64(42)
		buf := new(bytes.Buffer)
		err := binary.Write(buf, binary.LittleEndian, expected)
		require.NoError(t, err)

		result, err := decodeValue[int64](buf.Bytes())
		require.NoError(t, err)
		assert.Equal(t, expected, result)
	})

	t.Run("DecodeFloat64", func(t *testing.T) {
		expected := 3.14159
		buf := new(bytes.Buffer)
		err := binary.Write(buf, binary.LittleEndian, expected)
		require.NoError(t, err)

		result, err := decodeValue[float64](buf.Bytes())
		require.NoError(t, err)
		assert.Equal(t, expected, result)
	})

	t.Run("DecodeNegativeInt64", func(t *testing.T) {
		expected := int64(-100)
		buf := new(bytes.Buffer)
		err := binary.Write(buf, binary.LittleEndian, expected)
		require.NoError(t, err)

		result, err := decodeValue[int64](buf.Bytes())
		require.NoError(t, err)
		assert.Equal(t, expected, result)
	})

	t.Run("DecodeNaN", func(t *testing.T) {
		expected := math.NaN()
		buf := new(bytes.Buffer)
		err := binary.Write(buf, binary.LittleEndian, expected)
		require.NoError(t, err)

		result, err := decodeValue[float64](buf.Bytes())
		require.NoError(t, err)
		assert.True(t, math.IsNaN(result))
	})

	t.Run("DecodeInfinity", func(t *testing.T) {
		expected := math.Inf(1)
		buf := new(bytes.Buffer)
		err := binary.Write(buf, binary.LittleEndian, expected)
		require.NoError(t, err)

		result, err := decodeValue[float64](buf.Bytes())
		require.NoError(t, err)
		assert.Equal(t, expected, result)
	})

	t.Run("InvalidData", func(t *testing.T) {
		// Try to decode insufficient bytes
		_, err := decodeValue[int64]([]byte{1, 2, 3}) // int64 needs 8 bytes
		assert.Error(t, err)
	})
}

func TestParquetPartitionReader_WithHistoryPageRange(t *testing.T) {
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			{Name: "value", Type: arrow.PrimitiveTypes.Float64},
		},
		nil,
	)
	data := []map[string]any{
		{"_step": 0, "value": 0.0},
		{"_step": 10, "value": 10.0},
		{"_step": 20, "value": 20.0},
		{"_step": 30, "value": 30.0},
		{"_step": 40, "value": 40.0},
		{"_step": 50, "value": 50.0},
	}
	historyFilePath := filepath.Join(t.TempDir(), "test.parquet")
	test.CreateTestParquetFileFromData(t, historyFilePath, schema, data)
	pf, err := LocalParquetFile(historyFilePath, true)
	require.NoError(t, err)

	pageOpt := WithHistoryPageRange(HistoryPageParams{
		MinStep: 10,
		MaxStep: 30,
		Samples: 10,
	})

	reader := NewParquetPartitionReader(t.Context(), pf, []string{}, pageOpt)
	defer reader.Release()

	// Read all rows and verify they're within the range
	values := make([]KVMapList, 0)
	for value, err := range reader.All() {
		assert.NoError(t, err)
		values = append(values, value)
	}
	assert.Equal(t, 2, len(values))
	assert.Equal(
		t,
		[]KVMapList{
			{
				{Key: "_step", Value: int64(10)},
				{Key: "value", Value: float64(10)},
			},
			{
				{Key: "_step", Value: int64(20)},
				{Key: "value", Value: float64(20)},
			},
		},
		values,
	)
}

func TestParquetPartitionReader_EmptyFile(t *testing.T) {
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			{Name: "value", Type: arrow.PrimitiveTypes.Float64},
		},
		nil,
	)
	data := []map[string]any{}
	historyFilePath := filepath.Join(t.TempDir(), "test.parquet")
	test.CreateTestParquetFileFromData(t, historyFilePath, schema, data)
	pf, err := LocalParquetFile(historyFilePath, true)
	require.NoError(t, err)

	reader := NewParquetPartitionReader(t.Context(), pf, []string{}, nil)

	meta, err := reader.MetaData()
	assert.NoError(t, err)
	assert.Equal(t, 1, len(meta.RowGroups))
	assert.Equal(t, int64(0), meta.NumRows)

	// Verify no data is returned
	values := make([]KVMapList, 0)
	for value, err := range reader.All() {
		assert.NoError(t, err)
		values = append(values, value)
	}
	assert.Equal(t, 0, len(values))

	assert.NotPanics(t, func() {
		reader.Release()
	})
}
