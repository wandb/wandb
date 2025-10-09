package iterator

import (
	"testing"

	"github.com/apache/arrow-go/v18/arrow"
	"github.com/apache/arrow-go/v18/arrow/array"
	"github.com/apache/arrow-go/v18/arrow/memory"
	"github.com/stretchr/testify/assert"
)

func TestScalarIterator(t *testing.T) {
	vals := []int64{1, 2, 3}
	arr := array.NewInt64Builder(memory.DefaultAllocator)
	arr.AppendValues(vals, nil)
	ints := arr.NewArray()
	defer ints.Release()

	it := newScalarIterator(ints, int64Accessor)

	i := 0
	for it.Next() {
		assert.Equal(t, vals[i], it.Value())
		i++
	}
}

func TestListIterator(t *testing.T) {
	vals := [][]int64{
		{1, 2, 3},
		{4, 5, 6},
	}

	lb := array.NewListBuilder(
		memory.DefaultAllocator,
		arrow.PrimitiveTypes.Int64,
	)
	defer lb.Release()
	vb := lb.ValueBuilder().(*array.Int64Builder)
	for _, val := range vals {
		lb.Append(true)
		vb.AppendValues(val, nil)
	}
	list := lb.NewArray()
	defer list.Release()

	// Test the list iterator
	it, err := newListIterator(list)

	assert.NoError(t, err)
	i := 0
	for it.Next() {
		result := it.Value().([]any)
		assert.Equal(t, len(vals[i]), len(result))
		for j, v := range vals[i] {
			assert.Equal(t, v, result[j])
		}
		i++
	}
	assert.Equal(t, len(vals), i)
}

func TestStructIterator(t *testing.T) {
	vals := []map[string]any{
		{"a": int64(1), "b": int64(2)},
		{"a": int64(3), "b": int64(4)},
	}
	sb := array.NewStructBuilder(
		memory.DefaultAllocator,
		arrow.StructOf(
			arrow.Field{Name: "a", Type: arrow.PrimitiveTypes.Int64},
			arrow.Field{Name: "b", Type: arrow.PrimitiveTypes.Int64},
		),
	)
	defer sb.Release()
	aBuilder := sb.FieldBuilder(0).(*array.Int64Builder)
	bBuilder := sb.FieldBuilder(1).(*array.Int64Builder)
	for _, val := range vals {
		sb.Append(true)
		aBuilder.Append(val["a"].(int64))
		bBuilder.Append(val["b"].(int64))
	}
	structs := sb.NewArray()
	defer structs.Release()

	it, err := newStructIterator(structs)

	assert.NoError(t, err)
	i := 0
	for it.Next() {
		assert.Equal(t, vals[i], it.Value().(map[string]any))
		assert.Equal(
			t,
			vals[i]["a"],
			it.Value().(map[string]any)["a"],
		)
		assert.Equal(
			t,
			vals[i]["b"],
			it.Value().(map[string]any)["b"],
		)
		i++
	}
	assert.Equal(t, len(vals), i)
}
