package iterator

import (
	"encoding/json"
	"fmt"
	"math"
	"time"

	"github.com/apache/arrow-go/v18/arrow"
	"github.com/apache/arrow-go/v18/arrow/array"
)

// columnIterator is the interface used to iterate over the values in a single
// column. The values across columns should be merged together to form a single
// row.
type columnIterator interface {
	Next() bool
	Value() any
}

type columnIteratorConfig struct {
	returnRawBinary bool
}

// newColumnIterator returns the concrete struct responsible for iterating over
// a single arrow.Array (values for a single data chunk in a single column).
func newColumnIterator(data arrow.Array, config columnIteratorConfig) (columnIterator, error) {
	switch data.DataType().(type) {
	case *arrow.StructType:
		return newStructIterator(data, config)
	case *arrow.ListType:
		return newListIterator(data, config)
	case *arrow.Int32Type:
		return newScalarIterator(data, int32Accessor), nil
	case *arrow.Int64Type:
		return newScalarIterator(data, int64Accessor), nil
	case *arrow.Uint32Type:
		return newScalarIterator(data, uint32Accessor), nil
	case *arrow.Uint64Type:
		return newScalarIterator(data, uint64Accessor), nil
	case *arrow.Float32Type:
		return newScalarIterator(data, float32Accessor), nil
	case *arrow.Float64Type:
		return newScalarIterator(data, float64Accessor), nil
	case *arrow.StringType:
		return newScalarIterator(data, stringAccessor), nil
	case *arrow.BinaryType:
		if config.returnRawBinary {
			return newScalarIterator(data, rawBinaryAccessor), nil
		}
		return newScalarIterator(data, binaryAccessor), nil
	case *arrow.FixedSizeBinaryType:
		return newScalarIterator(data, fixedBinaryAccessor), nil
	case *arrow.BooleanType:
		return newScalarIterator(data, booleanAccessor), nil
	case *arrow.Time64Type:
		return newScalarIterator(data, time64Accessor), nil
	}
	return nil, fmt.Errorf("unsupported column type: %T", data.DataType)
}

type structIterator struct {
	data   *array.Struct
	offset int
	typ    *arrow.StructType

	children []columnIterator
	config   columnIteratorConfig
}

func newStructIterator(data arrow.Array, config columnIteratorConfig) (*structIterator, error) {
	arr := data.(*array.Struct)
	children := make([]columnIterator, arr.NumField())
	typ := data.DataType().(*arrow.StructType)
	var err error
	for i := 0; i < arr.NumField(); i++ {
		children[i], err = newColumnIterator(arr.Field(i), config)
		if err != nil {
			return nil, fmt.Errorf("%s > %w", typ.Field(i).Name, err)
		}
	}
	return &structIterator{
		data:     arr,
		typ:      typ,
		offset:   -1,
		children: children,
		config:   config,
	}, nil
}

func (s *structIterator) Next() bool {
	s.offset++
	if s.offset >= s.data.Len() {
		return false
	}
	next := false
	for _, c := range s.children {
		if c.Next() {
			next = true
		}
	}
	return next
}

func (s *structIterator) Value() interface{} {
	if s.data.IsNull(s.offset) {
		return nil
	}
	result := map[string]interface{}{}
	for i, c := range s.children {
		v := c.Value()
		if v != nil {
			result[s.typ.Field(i).Name] = c.Value()
		}
	}
	return result
}

type listIterator struct {
	data   *array.List
	offset int
	config columnIteratorConfig
}

func newListIterator(data arrow.Array, config columnIteratorConfig) (*listIterator, error) {
	arr := data.(*array.List)
	_, err := newColumnIterator(arr.ListValues(), config)
	if err != nil {
		return nil, err
	}
	return &listIterator{
		data:   arr,
		offset: -1,
		config: config,
	}, nil
}

func (c *listIterator) Next() bool {
	c.offset++
	return c.offset < c.data.Len()
}

func (c *listIterator) Value() any {
	if c.data.IsNull(c.offset) {
		return nil
	}
	offset := c.data.Offset() + c.offset
	beg := int(c.data.Offsets()[offset])
	end := int(c.data.Offsets()[offset+1])
	if end <= beg {
		return []any{}
	}
	s := array.NewSlice(c.data.ListValues(), int64(beg), int64(end))
	defer s.Release()
	it, err := newColumnIterator(s, c.config)
	if err != nil {
		// we did check for errors in the constructor,
		// so there should not be any errors...
		panic(err)
	}
	values := make([]any, 0, end-beg)
	for it.Next() {
		values = append(values, it.Value())
	}
	return values
}

type accessorFunc func(arrow.Array, int) any

type scalarIterator struct {
	data   arrow.Array
	offset int

	accessor accessorFunc
}

func newScalarIterator(data arrow.Array, accessor accessorFunc) *scalarIterator {
	return &scalarIterator{
		data:   data,
		offset: -1,

		accessor: accessor,
	}
}

func (c *scalarIterator) Next() bool {
	c.offset++
	return c.offset < c.data.Len()
}

func (c *scalarIterator) Value() (value any) {
	defer func() {
		// A panic may occur when the underlying data array is corrupt,
		// e.g. index out of bounds panic even when c.offset < c.data.Len()
		// For now, just catch the panic and return nil to avoid killing the calling process.
		if p := recover(); p != nil {
			// TODO: Bubble up some sort of corruption indicator for observability
			value = nil
		}
	}()
	if c.data.IsNull(c.offset) {
		return nil
	}
	return c.accessor(c.data, c.offset)
}

func int32Accessor(data arrow.Array, offset int) any {
	return data.(*array.Int32).Value(offset)
}

func uint32Accessor(data arrow.Array, offset int) any {
	return data.(*array.Uint32).Value(offset)
}

func int64Accessor(data arrow.Array, offset int) any {
	return data.(*array.Int64).Value(offset)
}

func uint64Accessor(data arrow.Array, offset int) any {
	return data.(*array.Uint64).Value(offset)
}

func float32Accessor(data arrow.Array, offset int) any {
	return data.(*array.Float32).Value(offset)
}

func float64Accessor(data arrow.Array, offset int) any {
	value := data.(*array.Float64).Value(offset)
	// Check for special float values - can't use switch due to NaN comparison
	if math.IsNaN(value) {
		return "NaN"
	}
	if math.IsInf(value, -1) {
		return "-Infinity"
	}
	if math.IsInf(value, +1) {
		return "Infinity"
	}
	return value
}

func stringAccessor(data arrow.Array, offset int) any {
	return data.(*array.String).Value(offset)
}

func binaryAccessor(data arrow.Array, offset int) any {
	raw := data.(*array.Binary).Value(offset)
	var value []byte
	if err := json.Unmarshal(raw, &value); err != nil {
		return raw
	}
	return value
}

func rawBinaryAccessor(data arrow.Array, offset int) any {
	return data.(*array.Binary).Value(offset)
}

func fixedBinaryAccessor(data arrow.Array, offset int) any {
	return data.(*array.FixedSizeBinary).Value(offset)
}

func time64Accessor(data arrow.Array, offset int) any {
	ts := int64(data.(*array.Time64).Value(offset))
	return time.Unix(ts/1e9, ts%1e9)
}

func booleanAccessor(data arrow.Array, offset int) any {
	return data.(*array.Boolean).Value(offset)
}
