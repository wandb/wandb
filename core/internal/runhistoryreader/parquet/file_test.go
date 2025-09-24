package parquet

import (
	"encoding/binary"
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

	reader, err := LocalParquetFile(historyFilePath, true /* parallel */)
	assert.NoError(t, err)

	assert.NotNil(t, reader)
	assert.Equal(
		t,
		int64(3),
		reader.ParquetReader().MetaData().NumRows,
	)
	assert.Equal(
		t,
		2,
		reader.ParquetReader().MetaData().Schema.NumColumns(),
	)
}

func TestLocalParquetFile_EmptyFile(t *testing.T) {
	historyFilePath := filepath.Join(t.TempDir(), "test.parquet")
	_, err := os.Create(historyFilePath)
	require.NoError(t, err)

	_, err = LocalParquetFile(historyFilePath, true /* parallel */)
	assert.Error(t, err)
}

func TestLocalParquetFile_CorruptedFile(t *testing.T) {
	// This tests writes garbage metadata
	// causing the pyarrow reader to raise an error.
	// see https://parquet.apache.org/docs/file-format/
	historyFilePath := filepath.Join(t.TempDir(), "corrupted.parquet")
	file, err := os.Create(historyFilePath)
	require.NoError(t, err)
	defer file.Close()

	// Header magic bytes
	_, err = file.Write([]byte("PAR1"))
	require.NoError(t, err)

	// Garbage metadata
	corruptedData := make([]byte, 1000)
	for i := range corruptedData {
		corruptedData[i] = byte(i % 256)
	}
	_, err = file.Write(corruptedData)
	require.NoError(t, err)

	// Footer data
	metadataLength := int32(100)
	err = binary.Write(file, binary.LittleEndian, metadataLength)
	require.NoError(t, err)
	_, err = file.Write([]byte("PAR1"))
	require.NoError(t, err)
	file.Close()

	// Try to open this corrupted file
	pf, err := LocalParquetFile(historyFilePath, true)
	assert.Error(t, err)
	assert.Nil(t, pf)
}
