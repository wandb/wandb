package historyparquet

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/apache/arrow-go/v18/arrow"
	"github.com/apache/arrow-go/v18/arrow/array"
	"github.com/apache/arrow-go/v18/arrow/memory"
	"github.com/apache/arrow-go/v18/parquet"
	"github.com/apache/arrow-go/v18/parquet/pqarrow"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// createTestParquetFile creates a simple parquet file for testing
func createTestParquetFile(t *testing.T, filepath string) {
	// Create a simple Arrow schema
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			{Name: "test_metric", Type: arrow.PrimitiveTypes.Float64},
		},
		nil,
	)

	// Create arrays directly
	alloc := memory.DefaultAllocator

	// Create int64 array for _step column
	stepBuilder := array.NewInt64Builder(alloc)
	defer stepBuilder.Release()
	stepBuilder.AppendValues([]int64{1, 2, 3}, nil)
	stepArray := stepBuilder.NewArray()
	defer stepArray.Release()

	// Create float64 array for test_metric column
	metricBuilder := array.NewFloat64Builder(alloc)
	defer metricBuilder.Release()
	metricBuilder.AppendValues([]float64{1.0, 2.0, 3.0}, nil)
	metricArray := metricBuilder.NewArray()
	defer metricArray.Release()

	// Create record batch from arrays
	record := array.NewRecordBatch(
		schema,
		[]arrow.Array{stepArray, metricArray},
		3,
	)
	defer record.Release()

	// Write to parquet file
	outFile, err := os.Create(filepath)
	require.NoError(t, err)
	defer outFile.Close()

	writer, err := pqarrow.NewFileWriter(
		schema,
		outFile,
		parquet.NewWriterProperties(),
		pqarrow.DefaultWriterProps(),
	)
	require.NoError(t, err)
	defer writer.Close()

	err = writer.Write(record)
	require.NoError(t, err)
}

func TestLocalParquetFile_MetaData(t *testing.T) {
	historyFilePath := filepath.Join(t.TempDir(), "test.parquet")
	createTestParquetFile(t, historyFilePath)

	pf, err := LocalParquetFile(historyFilePath, true /* parallel */)
	assert.NoError(t, err)
	defer pf.Close()

	assert.NotNil(t, pf)
	assert.NotNil(t, pf.reader)
	assert.Equal(
		t,
		int64(3),
		pf.reader.ParquetReader().MetaData().NumRows,
	)
	assert.Equal(
		t,
		2,
		pf.reader.ParquetReader().MetaData().Schema.NumColumns(),
	)
}
