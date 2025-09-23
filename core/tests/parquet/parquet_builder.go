package test

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
// data can be:
// - []map[string]any: each map represents a row with field names as keys
// - [][]any: each inner slice represents a row with values in schema field order
func CreateTestParquetFileFromData(
	t *testing.T,
	filepath string,
	schema *arrow.Schema,
	data []map[string]any,
) {
	if len(data) == 0 {
		t.Fatal("cannot create parquet file with no data")
	}

	alloc := memory.DefaultAllocator

	// Build arrays for each field in the schema
	builders := make([]array.Builder, schema.NumFields())
	for i, field := range schema.Fields() {
		builder := createBuilderForType(alloc, field.Type)
		if builder == nil {
			t.Fatalf("unsupported type for field %s: %v", field.Name, field.Type)
		}
		builders[i] = builder
	}
	defer func() {
		for _, b := range builders {
			b.Release()
		}
	}()

	// Populate builders with data
	for _, row := range data {
		for i, field := range schema.Fields() {
			value := row[field.Name]
			appendToBuilder(t, builders[i], value, field.Type)
		}
	}

	// Create arrays from builders
	arrays := make([]arrow.Array, len(builders))
	for i, builder := range builders {
		arrays[i] = builder.NewArray()
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

// createBuilderForType creates an appropriate builder for the given Arrow type
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

// appendToBuilder appends a value to the appropriate builder
func appendToBuilder(t *testing.T, builder array.Builder, value any, dataType arrow.DataType) {
	// Handle nil values
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
		switch v := value.(type) {
		case int64:
			b.Append(v)
		case int:
			b.Append(int64(v))
		case int32:
			b.Append(int64(v))
		case float64:
			// Handle float64 to int64 conversion (useful for JSON deserialization)
			b.Append(int64(v))
		default:
			t.Fatalf("cannot convert %T to int64", value)
		}
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
	case *array.StringBuilder:
		b.Append(value.(string))
	case *array.BinaryBuilder:
		b.Append(value.([]byte))
	case *array.ListBuilder:
		listVal, ok := value.([]any)
		if !ok {
			// Handle empty list or other types
			t.Fatalf("expected []any for list builder, got %T", value)
		}
		b.Append(true)
		elemType := dataType.(*arrow.ListType).Elem()
		for _, elem := range listVal {
			appendToBuilder(t, b.ValueBuilder(), elem, elemType)
		}
	case *array.StructBuilder:
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
	default:
		t.Fatalf("unsupported builder type %T", builder)
	}
}

// BuildListOfStructsArray creates an Arrow array of type List<Struct> for testing
// This can handle two input formats:
// 1. Direct values: []any{nil, []any{...}, ...}
// 2. Map format: []map[string]any{{"fieldName": value}, ...}
func BuildListOfStructsArray(
	t *testing.T,
	listType arrow.DataType, // Should be arrow.ListOf(arrow.StructOf(...))
	values any, // Can be []any or []map[string]any
) arrow.Array {
	alloc := memory.DefaultAllocator

	// Extract the struct type from the list type
	var structType *arrow.StructType
	switch lt := listType.(type) {
	case *arrow.ListType:
		structType = lt.Elem().(*arrow.StructType)
	default:
		t.Fatalf("expected ListType, got %T", listType)
	}

	// Create the list builder
	listBuilder := array.NewListBuilder(alloc, structType)
	defer listBuilder.Release()

	// Get the struct builder for the list values
	structBuilder := listBuilder.ValueBuilder().(*array.StructBuilder)

	// Handle different input formats
	switch v := values.(type) {
	case []map[string]any:
		// Map format - extract the field name from the map
		// Assume the map has a single key which is the field name
		for _, mapValue := range v {
			// Find the field name (should be the key in the map)
			var fieldValue any
			for _, val := range mapValue {
				fieldValue = val
				break // Assuming single field in the map
			}

			if fieldValue == nil {
				// Append null list
				listBuilder.AppendNull()
			} else {
				// Start a new list
				listBuilder.Append(true)

				// fieldValue should be []any containing maps
				listItems, ok := fieldValue.([]any)
				if !ok {
					t.Fatalf("expected []any, got %T", fieldValue)
				}

				// Add each struct to the list
				for _, item := range listItems {
					structData, ok := item.(map[string]any)
					if !ok {
						t.Fatalf("expected map[string]any, got %T", item)
					}

					// Append the struct
					structBuilder.Append(true)

					// Fill in the struct fields
					for i, field := range structType.Fields() {
						if fieldVal, exists := structData[field.Name]; exists {
							appendFieldValue(t, structBuilder.FieldBuilder(i), fieldVal)
						} else {
							t.Fatalf("missing '%s' field in struct", field.Name)
						}
					}
				}
			}
		}

	case []any:
		// Direct values format
		for _, value := range v {
			if value == nil {
				// Append null list
				listBuilder.AppendNull()
			} else {
				// Start a new list
				listBuilder.Append(true)

				// value should be []any containing maps
				listItems, ok := value.([]any)
				if !ok {
					t.Fatalf("expected []any, got %T", value)
				}

				// Add each struct to the list
				for _, item := range listItems {
					structData, ok := item.(map[string]any)
					if !ok {
						t.Fatalf("expected map[string]any, got %T", item)
					}

					// Append the struct
					structBuilder.Append(true)

					// Fill in the struct fields
					for i, field := range structType.Fields() {
						if fieldVal, exists := structData[field.Name]; exists {
							appendFieldValue(t, structBuilder.FieldBuilder(i), fieldVal)
						} else {
							t.Fatalf("missing '%s' field in struct", field.Name)
						}
					}
				}
			}
		}

	default:
		t.Fatalf("unsupported values type %T", values)
	}

	return listBuilder.NewArray()
}

// appendFieldValue is a helper function to append values to different types of field builders
func appendFieldValue(t *testing.T, fb array.Builder, value any) {
	switch builder := fb.(type) {
	case *array.Int64Builder:
		builder.Append(value.(int64))
	case *array.Int32Builder:
		builder.Append(value.(int32))
	case *array.Float64Builder:
		builder.Append(value.(float64))
	case *array.Float32Builder:
		builder.Append(value.(float32))
	case *array.StringBuilder:
		builder.Append(value.(string))
	case *array.BooleanBuilder:
		builder.Append(value.(bool))
	default:
		t.Fatalf("unsupported field builder type %T", fb)
	}
}

// BuildArray creates an Arrow array with the given values for testing
func BuildArray[T float64 | float32 | int64 | int32 | int16 | int8 | uint64 | uint32 | uint16 | uint8](
	t *testing.T,
	values []T,
	valid []bool,
) arrow.Array {
	alloc := memory.DefaultAllocator
	var builder array.Builder

	// Create the appropriate builder based on the type
	switch any(values).(type) {
	case []float64:
		b := array.NewFloat64Builder(alloc)
		b.AppendValues(any(values).([]float64), valid)
		builder = b
	case []float32:
		b := array.NewFloat32Builder(alloc)
		b.AppendValues(any(values).([]float32), valid)
		builder = b
	case []int64:
		b := array.NewInt64Builder(alloc)
		b.AppendValues(any(values).([]int64), valid)
		builder = b
	case []int32:
		b := array.NewInt32Builder(alloc)
		b.AppendValues(any(values).([]int32), valid)
		builder = b
	case []int16:
		b := array.NewInt16Builder(alloc)
		b.AppendValues(any(values).([]int16), valid)
		builder = b
	case []int8:
		b := array.NewInt8Builder(alloc)
		b.AppendValues(any(values).([]int8), valid)
		builder = b
	case []uint64:
		b := array.NewUint64Builder(alloc)
		b.AppendValues(any(values).([]uint64), valid)
		builder = b
	case []uint32:
		b := array.NewUint32Builder(alloc)
		b.AppendValues(any(values).([]uint32), valid)
		builder = b
	case []uint16:
		b := array.NewUint16Builder(alloc)
		b.AppendValues(any(values).([]uint16), valid)
		builder = b
	case []uint8:
		b := array.NewUint8Builder(alloc)
		b.AppendValues(any(values).([]uint8), valid)
		builder = b
	default:
		t.Fatalf("unsupported type %T", values)
	}

	defer builder.Release()
	return builder.NewArray()
}

// CreateTestParquetFile creates a simple parquet file for testing
func CreateTestParquetFile(
	t *testing.T,
	filepath string,
	schema *arrow.Schema,
	arrays []arrow.Array,
) {
	// Create record batch from arrays
	record := array.NewRecordBatch(
		schema,
		arrays,
		int64(arrays[0].Len()),
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
