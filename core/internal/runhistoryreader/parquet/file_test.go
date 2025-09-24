package parquet

import (
	"bytes"
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
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
	data := []map[string]any{
		{"_step": 1, "test_metric": 1.0},
		{"_step": 2, "test_metric": 2.0},
		{"_step": 3, "test_metric": 3.0},
	}
	historyFilePath := filepath.Join(t.TempDir(), "test.parquet")
	test.CreateTestParquetFileFromData(t, historyFilePath, schema, data)

	pf, err := LocalParquetFile(historyFilePath, true /* parallel */)
	assert.NoError(t, err)
	assert.NotNil(t, pf)
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
	data := []map[string]any{
		{"_step": 1, "test_metric": 1.0},
		{"_step": 2, "test_metric": 2.0},
		{"_step": 3, "test_metric": 3.0},
	}
	historyFilePath := filepath.Join(t.TempDir(), "test.parquet")
	test.CreateTestParquetFileFromData(t, historyFilePath, schema, data)

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

// mockReaderAtSeeker is a mock implementation of parquet.ReaderAtSeeker for testing
type mockReaderAtSeeker struct {
	data      []byte
	pos       int64
	readErr   error
	seekErr   error
	readAtErr error
}

func newMockReaderAtSeeker(data []byte) *mockReaderAtSeeker {
	return &mockReaderAtSeeker{
		data: data,
		pos:  0,
	}
}

func (m *mockReaderAtSeeker) Read(p []byte) (n int, err error) {
	if m.readErr != nil {
		return 0, m.readErr
	}
	if m.pos >= int64(len(m.data)) {
		return 0, io.EOF
	}
	n = copy(p, m.data[m.pos:])
	m.pos += int64(n)
	return n, nil
}

func (m *mockReaderAtSeeker) Seek(offset int64, whence int) (int64, error) {
	if m.seekErr != nil {
		return 0, m.seekErr
	}
	var newPos int64
	switch whence {
	case io.SeekStart:
		newPos = offset
	case io.SeekCurrent:
		newPos = m.pos + offset
	case io.SeekEnd:
		newPos = int64(len(m.data)) + offset
	default:
		return 0, errors.New("invalid whence")
	}
	if newPos < 0 || newPos > int64(len(m.data)) {
		return 0, errors.New("seek out of range")
	}
	m.pos = newPos
	return m.pos, nil
}

func (m *mockReaderAtSeeker) ReadAt(p []byte, off int64) (n int, err error) {
	if m.readAtErr != nil {
		return 0, m.readAtErr
	}
	if off < 0 || off >= int64(len(m.data)) {
		return 0, io.EOF
	}
	n = copy(p, m.data[off:])
	if n < len(p) {
		err = io.EOF
	}
	return n, err
}

// createTestParquetData creates a parquet file in memory and returns its bytes
func createTestParquetData(t *testing.T) []byte {
	t.Helper()

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

	// Write to buffer
	var buf bytes.Buffer
	writer, err := pqarrow.NewFileWriter(
		schema,
		&buf,
		parquet.NewWriterProperties(),
		pqarrow.DefaultWriterProps(),
	)
	require.NoError(t, err)
	defer writer.Close()

	err = writer.Write(record)
	require.NoError(t, err)

	err = writer.Close()
	require.NoError(t, err)

	return buf.Bytes()
}

func TestRemoteParquetFile_ValidData(t *testing.T) {
	ctx := context.Background()
	parquetData := createTestParquetData(t)
	reader := newMockReaderAtSeeker(parquetData)

	pf, err := RemoteParquetFile(ctx, reader)
	assert.NoError(t, err)
	assert.NotNil(t, pf)
	defer pf.ParquetReader().Close()

	// Verify we can read the metadata
	assert.NotNil(t, pf.ParquetReader())
	assert.Equal(
		t,
		int64(3),
		pf.ParquetReader().MetaData().NumRows,
	)
	assert.Equal(
		t,
		2,
		pf.ParquetReader().MetaData().Schema.NumColumns(),
	)
}

func TestRemoteParquetFile_BytesReader(t *testing.T) {
	// Test with bytes.Reader which also implements parquet.ReaderAtSeeker
	ctx := context.Background()
	parquetData := createTestParquetData(t)
	reader := bytes.NewReader(parquetData)

	pf, err := RemoteParquetFile(ctx, reader)
	assert.NoError(t, err)
	assert.NotNil(t, pf)
	defer pf.ParquetReader().Close()

	// Verify we can read the arrow schema
	schema, err := pf.Schema()
	assert.NoError(t, err)
	assert.NotNil(t, schema)
	assert.Equal(t, 2, schema.NumFields())
	assert.Equal(t, "_step", schema.Field(0).Name)
	assert.Equal(t, "test_metric", schema.Field(1).Name)
}

func TestRemoteParquetFile_EmptyData(t *testing.T) {
	ctx := context.Background()
	emptyData := []byte{}
	reader := newMockReaderAtSeeker(emptyData)

	_, err := RemoteParquetFile(ctx, reader)
	assert.Error(t, err)
}

func TestRemoteParquetFile_InvalidData(t *testing.T) {
	ctx := context.Background()
	// Create invalid parquet data
	invalidData := []byte("this is not a parquet file")
	reader := newMockReaderAtSeeker(invalidData)

	_, err := RemoteParquetFile(ctx, reader)
	assert.Error(t, err)
}

func TestRemoteParquetFile_CorruptedParquetData(t *testing.T) {
	ctx := context.Background()

	// Create corrupted parquet data similar to the LocalParquetFile test
	var buf bytes.Buffer

	// Header magic bytes
	_, err := buf.Write([]byte("PAR1"))
	require.NoError(t, err)

	// Garbage metadata
	corruptedData := make([]byte, 1000)
	for i := range corruptedData {
		corruptedData[i] = byte(i % 256)
	}
	_, err = buf.Write(corruptedData)
	require.NoError(t, err)

	// Footer data
	metadataLength := int32(100)
	err = binary.Write(&buf, binary.LittleEndian, metadataLength)
	require.NoError(t, err)
	_, err = buf.Write([]byte("PAR1"))
	require.NoError(t, err)

	reader := newMockReaderAtSeeker(buf.Bytes())

	_, err = RemoteParquetFile(ctx, reader)
	assert.Error(t, err)
}

func TestRemoteParquetFile_ReadError(t *testing.T) {
	ctx := context.Background()
	parquetData := createTestParquetData(t)
	reader := newMockReaderAtSeeker(parquetData)
	// Set a read error
	reader.readAtErr = errors.New("simulated read error")

	_, err := RemoteParquetFile(ctx, reader)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "simulated read error")
}

func TestRemoteParquetFile_ContextCancellation(t *testing.T) {
	// Create a cancelled context
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	parquetData := createTestParquetData(t)
	reader := newMockReaderAtSeeker(parquetData)

	// The function should still work as it doesn't actively use context
	// This test documents current behavior
	pf, err := RemoteParquetFile(ctx, reader)
	assert.NoError(t, err)
	if pf != nil {
		defer pf.ParquetReader().Close()
	}
}

func TestRemoteParquetFile_ReadColumns(t *testing.T) {
	ctx := context.Background()
	parquetData := createTestParquetData(t)
	reader := newMockReaderAtSeeker(parquetData)

	pf, err := RemoteParquetFile(ctx, reader)
	assert.NoError(t, err)
	assert.NotNil(t, pf)
	defer pf.ParquetReader().Close()

	// Test reading specific columns
	colIndices := []int{0, 1}
	rowGroups := []int{0}

	tbl, err := pf.ReadRowGroups(context.Background(), colIndices, rowGroups)
	assert.NoError(t, err)
	assert.NotNil(t, tbl)
	defer tbl.Release()

	// Verify the table has the expected structure
	assert.Equal(t, int64(3), tbl.NumRows())
	assert.Equal(t, 2, int(tbl.NumCols()))

	// Verify column names
	schema := tbl.Schema()
	assert.Equal(t, "_step", schema.Field(0).Name)
	assert.Equal(t, "test_metric", schema.Field(1).Name)
}

func TestRemoteParquetFile_LargeFile(t *testing.T) {
	// Test with a larger parquet file to ensure proper handling
	ctx := context.Background()

	// Create a larger parquet file
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			{Name: "test_metric", Type: arrow.PrimitiveTypes.Float64},
			{Name: "test_string", Type: arrow.BinaryTypes.String},
		},
		nil,
	)

	alloc := memory.DefaultAllocator

	// Create arrays with more data
	stepBuilder := array.NewInt64Builder(alloc)
	defer stepBuilder.Release()
	metricBuilder := array.NewFloat64Builder(alloc)
	defer metricBuilder.Release()
	stringBuilder := array.NewStringBuilder(alloc)
	defer stringBuilder.Release()

	// Add 100 rows
	for i := 0; i < 100; i++ {
		stepBuilder.Append(int64(i))
		metricBuilder.Append(float64(i) * 1.5)
		stringBuilder.Append(fmt.Sprintf("value_%d", i))
	}

	stepArray := stepBuilder.NewArray()
	defer stepArray.Release()
	metricArray := metricBuilder.NewArray()
	defer metricArray.Release()
	stringArray := stringBuilder.NewArray()
	defer stringArray.Release()

	record := array.NewRecordBatch(
		schema,
		[]arrow.Array{stepArray, metricArray, stringArray},
		100,
	)
	defer record.Release()

	// Write to buffer
	var buf bytes.Buffer
	writer, err := pqarrow.NewFileWriter(
		schema,
		&buf,
		parquet.NewWriterProperties(),
		pqarrow.DefaultWriterProps(),
	)
	require.NoError(t, err)

	err = writer.Write(record)
	require.NoError(t, err)

	err = writer.Close()
	require.NoError(t, err)

	// Create reader from buffer
	reader := bytes.NewReader(buf.Bytes())

	pf, err := RemoteParquetFile(ctx, reader)
	assert.NoError(t, err)
	assert.NotNil(t, pf)
	defer pf.ParquetReader().Close()

	// Verify metadata
	assert.Equal(t, int64(100), pf.ParquetReader().MetaData().NumRows)
	assert.Equal(t, 3, pf.ParquetReader().MetaData().Schema.NumColumns())

	// Verify we can read the data
	tbl, err := pf.ReadTable(context.Background())
	assert.NoError(t, err)
	assert.NotNil(t, tbl)
	defer tbl.Release()

	assert.Equal(t, int64(100), tbl.NumRows())
	assert.Equal(t, 3, int(tbl.NumCols()))
}

func TestRemoteParquetFile_SeekOperations(t *testing.T) {
	// Test that the reader properly handles seek operations
	ctx := context.Background()
	parquetData := createTestParquetData(t)
	reader := newMockReaderAtSeeker(parquetData)

	// Perform some seek operations before creating the parquet reader
	_, err := reader.Seek(10, io.SeekStart)
	assert.NoError(t, err)
	_, err = reader.Seek(0, io.SeekStart) // Reset to beginning
	assert.NoError(t, err)

	pf, err := RemoteParquetFile(ctx, reader)
	assert.NoError(t, err)
	assert.NotNil(t, pf)
	defer pf.ParquetReader().Close()

	// Verify we can still read metadata correctly after seeks
	assert.Equal(
		t,
		int64(3),
		pf.ParquetReader().MetaData().NumRows,
	)
}
