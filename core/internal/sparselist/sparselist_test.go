package sparselist_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/sparselist"
)

func TestSparseList(t *testing.T) {
	list := sparselist.SparseList[string]{}

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
	emptyList := sparselist.SparseList[string]{}

	assert.Equal(t,
		[]sparselist.Run[string]{},
		emptyList.ToRuns())
}

func TestSparseListUpdate(t *testing.T) {
	list1 := sparselist.SparseList[string]{}
	list1.Put(0, "a")
	list1.Put(1, "b")
	list1.Put(2, "c")
	list2 := sparselist.SparseList[string]{}
	list2.Put(1, "x")
	list2.Put(3, "y")

	list1.Update(list2)

	assert.Equal(t,
		[]sparselist.Run[string]{
			{Start: 0, Items: []string{"a", "x", "c", "y"}},
		},
		list1.ToRuns())
}
