package runhistoryreadertest

// parquet_builder.go is a utility for creating parquet files used for testing
// from data that looks similar to data logged by run.log().

import (
	"os"
	"testing"

	"github.com/apache/arrow-go/v18/arrow"
	"github.com/apache/arrow-go/v18/arrow/array"
	"github.com/apache/arrow-go/v18/arrow/memory"
	"github.com/apache/arrow-go/v18/parquet"
	"github.com/apache/arrow-go/v18/parquet/pqarrow"
	"github.com/stretchr/testify/require"
)

// CreateTestParquetFile creates a parquet file using the provided schema and data
func CreateTestParquetFileFromData(
	t *testing.T,
	filepath string,
	schema *arrow.Schema,
	data []map[string]any,
) {
	builders := make([]array.Builder, 0, schema.NumFields())
	for _, field := range schema.Fields() {
		builder := createBuilderForType(memory.DefaultAllocator, field.Type)
		if builder == nil {
			t.Fatalf(
				"unsupported type for field %s: %v",
				field.Name,
				field.Type,
			)
		}
		builders = append(builders, builder)
	}
	defer func() {
		for _, b := range builders {
			b.Release()
		}
	}()

	// Populate builders with data
	num := 0
	for _, row := range data {
		for i, field := range schema.Fields() {
			value := row[field.Name]
			appendToBuilder(t, builders[i], value, field.Type)
			num++
		}
	}

	// Create arrays from builders
	arrays := make([]arrow.Array, 0, len(builders))
	for _, builder := range builders {
		arrays = append(arrays, builder.NewArray())
	}
	defer func() {
		for _, arr := range arrays {
			arr.Release()
		}
	}()

	// Create record batch
	numRows := int64(len(data))
	record := array.NewRecordBatch(schema, arrays, numRows)
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

func createBuilderForType(alloc memory.Allocator, dataType arrow.DataType) array.Builder {
	switch dt := dataType.(type) {
	case *arrow.BooleanType:
		return array.NewBooleanBuilder(alloc)
	case *arrow.Int8Type:
		return array.NewInt8Builder(alloc)
	case *arrow.Int16Type:
		return array.NewInt16Builder(alloc)
	case *arrow.Int32Type:
		return array.NewInt32Builder(alloc)
	case *arrow.Int64Type:
		return array.NewInt64Builder(alloc)
	case *arrow.Uint8Type:
		return array.NewUint8Builder(alloc)
	case *arrow.Uint16Type:
		return array.NewUint16Builder(alloc)
	case *arrow.Uint32Type:
		return array.NewUint32Builder(alloc)
	case *arrow.Uint64Type:
		return array.NewUint64Builder(alloc)
	case *arrow.Float32Type:
		return array.NewFloat32Builder(alloc)
	case *arrow.Float64Type:
		return array.NewFloat64Builder(alloc)
	case *arrow.StringType:
		return array.NewStringBuilder(alloc)
	case *arrow.BinaryType:
		return array.NewBinaryBuilder(alloc, arrow.BinaryTypes.Binary)
	case *arrow.ListType:
		return array.NewListBuilder(alloc, dt.Elem())
	case *arrow.StructType:
		return array.NewStructBuilder(alloc, dt)
	default:
		return nil
	}
}

// appendInt64Value handles conversion and appending of int64 values
func appendInt64Value(t *testing.T, b *array.Int64Builder, value any) {
	switch v := value.(type) {
	case int64:
		b.Append(v)
	case int:
		b.Append(int64(v))
	case int32:
		b.Append(int64(v))
	case float64:
		b.Append(int64(v))
	default:
		t.Fatalf("cannot convert %T to int64", value)
	}
}

// appendFloat64Value handles conversion and appending of float64 values
func appendFloat64Value(t *testing.T, b *array.Float64Builder, value any) {
	switch v := value.(type) {
	case float64:
		b.Append(v)
	case float32:
		b.Append(float64(v))
	case int:
		b.Append(float64(v))
	default:
		t.Fatalf("cannot convert %T to float64", value)
	}
}

// appendListValue handles appending list values
func appendListValue(t *testing.T, b *array.ListBuilder, value any, dataType arrow.DataType) {
	listVal, ok := value.([]any)
	if !ok {
		t.Fatalf("expected []any for list builder, got %T", value)
	}
	b.Append(true)
	elemType := dataType.(*arrow.ListType).Elem()
	for _, elem := range listVal {
		appendToBuilder(t, b.ValueBuilder(), elem, elemType)
	}
}

// appendStructValue handles appending struct values
func appendStructValue(t *testing.T, b *array.StructBuilder, value any, dataType arrow.DataType) {
	structVal, ok := value.(map[string]any)
	if !ok {
		t.Fatalf("expected map[string]any for struct builder, got %T", value)
	}
	b.Append(true)
	structType := dataType.(*arrow.StructType)
	for i, field := range structType.Fields() {
		fieldBuilder := b.FieldBuilder(i)
		if fieldVal, exists := structVal[field.Name]; exists {
			appendToBuilder(t, fieldBuilder, fieldVal, field.Type)
		} else {
			fieldBuilder.AppendNull()
		}
	}
}

func appendToBuilder(t *testing.T, builder array.Builder, value any, dataType arrow.DataType) {
	if value == nil {
		builder.AppendNull()
		return
	}

	switch b := builder.(type) {
	case *array.BooleanBuilder:
		b.Append(value.(bool))
	case *array.Int8Builder:
		b.Append(value.(int8))
	case *array.Int16Builder:
		b.Append(value.(int16))
	case *array.Int32Builder:
		b.Append(value.(int32))
	case *array.Int64Builder:
		appendInt64Value(t, b, value)
	case *array.Uint8Builder:
		b.Append(value.(uint8))
	case *array.Uint16Builder:
		b.Append(value.(uint16))
	case *array.Uint32Builder:
		b.Append(value.(uint32))
	case *array.Uint64Builder:
		b.Append(value.(uint64))
	case *array.Float32Builder:
		b.Append(value.(float32))
	case *array.Float64Builder:
		appendFloat64Value(t, b, value)
	case *array.StringBuilder:
		b.Append(value.(string))
	case *array.BinaryBuilder:
		b.Append(value.([]byte))
	case *array.ListBuilder:
		appendListValue(t, b, value, dataType)
	case *array.StructBuilder:
		appendStructValue(t, b, value, dataType)
	default:
		t.Fatalf("unsupported builder type %T", builder)
	}
}
