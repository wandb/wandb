package parquet

import (
	"encoding/binary"
	"os"
	"path/filepath"
	"testing"

	"github.com/apache/arrow-go/v18/arrow"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	test "github.com/wandb/wandb/core/tests/parquet"
)

func TestLocalParquetFile_Reader_NoError(t *testing.T) {
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			{Name: "test_metric", Type: arrow.PrimitiveTypes.Float64},
		},
		nil,
	)
	arrays := []arrow.Array{
		test.BuildArray(t, []int64{1, 2, 3}, nil),
		test.BuildArray(t, []float64{1.0, 2.0, 3.0}, nil),
	}

	historyFilePath := filepath.Join(t.TempDir(), "test.parquet")
	test.CreateTestParquetFile(t, historyFilePath, schema, arrays)

	pf, err := LocalParquetFile(historyFilePath, true /* parallel */)
	assert.NoError(t, err)
	defer pf.Close()
	assert.NotNil(t, pf)
	assert.NotNil(t, pf.reader)
}

func TestLocalParquetFile_Reader_Error(t *testing.T) {
	pf, err := LocalParquetFile("nonexistent.parquet", true /* parallel */)
	assert.Error(t, err)
	assert.Nil(t, pf)
}

func TestLocalParquetFile_MetaData(t *testing.T) {
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			{Name: "test_metric", Type: arrow.PrimitiveTypes.Float64},
		},
		nil,
	)
	arrays := []arrow.Array{
		test.BuildArray(t, []int64{1, 2, 3}, nil),
		test.BuildArray(t, []float64{1.0, 2.0, 3.0}, nil),
	}

	historyFilePath := filepath.Join(t.TempDir(), "test.parquet")
	test.CreateTestParquetFile(t, historyFilePath, schema, arrays)

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
