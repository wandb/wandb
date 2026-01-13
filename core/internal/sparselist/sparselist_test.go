package sparselist_test

import (
	"maps"
	"slices"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/sparselist"
)

func TestNilSparseList(t *testing.T) {
	var nilList *sparselist.SparseList[string]

	assert.Equal(t, 0, nilList.Len())
	assert.Equal(t, 0, nilList.FirstIndex())
	assert.Equal(t, 0, nilList.LastIndex())

	assert.Zero(t, nilList.GetOrZero(0))
	s, ok := nilList.Get(0)
	assert.Zero(t, s)
	assert.False(t, ok)

	assert.Empty(t, maps.Collect(nilList.FirstRun()))
	assert.Empty(t, slices.Collect(nilList.FirstRunValues()))
	nilList.ForEach(func(i int, s string) { t.Fatal("shouldn't run") })

	assert.Empty(t, nilList.ToRuns())
	assert.Empty(t, nilList.ToMap())

	list := &sparselist.SparseList[string]{}
	assert.NotPanics(t, func() { list.Update(nilList) })
}

func TestSparseListGet(t *testing.T) {
	list := &sparselist.SparseList[string]{}

	_, existed := list.Get(0)
	assert.False(t, existed)

	list.Put(0, "xyz")
	val, existed := list.Get(0)
	assert.True(t, existed)
	assert.Equal(t, "xyz", val)
}

func TestSparseListRuns(t *testing.T) {
	list := &sparselist.SparseList[string]{}

	list.Put(0, "zero")
	list.Put(1, "one")
	list.Put(2, "two")
	list.Put(3, "three")
	list.Put(4, "four")
	list.Delete(2)

	assert.Equal(t,
		[]sparselist.Run[string]{
			{Start: 0, Items: []string{"zero", "one"}},
			{Start: 3, Items: []string{"three", "four"}},
		},
		list.ToRuns())
}

func TestSparseListEmpty(t *testing.T) {
	emptyList := &sparselist.SparseList[string]{}

	assert.Equal(t,
		[]sparselist.Run[string]{},
		emptyList.ToRuns())
}

func TestSparseListUpdate(t *testing.T) {
	list1 := &sparselist.SparseList[string]{}
	list1.Put(0, "a")
	list1.Put(1, "b")
	list1.Put(2, "c")
	list2 := &sparselist.SparseList[string]{}
	list2.Put(1, "x")
	list2.Put(3, "y")

	list1.Update(list2)

	assert.Equal(t,
		map[int]string{0: "a", 1: "x", 2: "c", 3: "y"},
		list1.ToMap())
}

func TestSparseListIndices(t *testing.T) {
	list := &sparselist.SparseList[string]{}

	list.Put(-1, "a")
	list.Put(99, "b")
	list.Put(5, "b")
	list.Put(109, "b")
	list.Put(-3, "b")
	list.Put(10, "b")

	assert.Equal(t, -3, list.FirstIndex())
	assert.Equal(t, 109, list.LastIndex())

	list.Delete(-3)
	assert.Equal(t, -1, list.FirstIndex())

	list.Delete(109)
	assert.Equal(t, 99, list.LastIndex())
}

func TestSparseListMap(t *testing.T) {
	list := &sparselist.SparseList[float64]{}
	list.Put(0, 1.23)
	list.Put(1, 4.56)
	list.Put(2, 7.89)

	result := sparselist.Map(list,
		func(x float64) float64 { return -x })

	assert.Equal(t,
		map[int]float64{0: -1.23, 1: -4.56, 2: -7.89},
		result.ToMap())
}
