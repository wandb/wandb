package collections_test

import (
	"iter"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/collections"
)

func TestAppend_IncreasesLength(t *testing.T) {
	list := &collections.DoublyLinkedList[int]{}

	_ = list.Append(1)
	_ = list.Append(1)
	_ = list.Append(1)

	assert.Equal(t, list.Len(), 3)
}

func TestRemove_ReducesLength(t *testing.T) {
	list := &collections.DoublyLinkedList[int]{}

	_ = list.Append(1)
	n := list.Append(1)
	_ = list.Append(1)
	n.Remove()

	assert.Equal(t, list.Len(), 2)
}

func TestRemoveInMiddle_RemovedFromIter(t *testing.T) {
	list := &collections.DoublyLinkedList[string]{}

	_ = list.Append("one")
	n := list.Append("two")
	_ = list.Append("three")
	n.Remove()

	next, stop := iter.Pull2(list.Iter())
	defer stop()

	i, x, ok := next()
	assert.Equal(t, 0, i)
	assert.Equal(t, "one", x)
	assert.True(t, ok)
	i, x, ok = next()
	assert.Equal(t, 1, i)
	assert.Equal(t, "three", x)
	assert.True(t, ok)
	_, _, ok = next()
	assert.False(t, ok)
}

func TestAppendAfterRemove(t *testing.T) {
	list := &collections.DoublyLinkedList[string]{}

	_ = list.Append("one")
	n2 := list.Append("two")
	n3 := list.Append("three")
	n2.Remove()
	n3.Remove()
	_ = list.Append("four")

	next, stop := iter.Pull2(list.Iter())
	defer stop()

	i, x, ok := next()
	assert.Equal(t, 0, i)
	assert.Equal(t, "one", x)
	assert.True(t, ok)
	i, x, ok = next()
	assert.Equal(t, 1, i)
	assert.Equal(t, "four", x)
	assert.True(t, ok)
	_, _, ok = next()
	assert.False(t, ok)
}

func TestRemoveFirst_RemovedFromIter(t *testing.T) {
	list := &collections.DoublyLinkedList[string]{}

	n := list.Append("one")
	_ = list.Append("two")
	_ = list.Append("three")
	n.Remove()

	next, stop := iter.Pull2(list.Iter())
	defer stop()

	i, x, ok := next()
	assert.Equal(t, 0, i)
	assert.Equal(t, "two", x)
	assert.True(t, ok)
	i, x, ok = next()
	assert.Equal(t, 1, i)
	assert.Equal(t, "three", x)
	assert.True(t, ok)
	_, _, ok = next()
	assert.False(t, ok)
}

func TestRemoveLast_RemovedFromIter(t *testing.T) {
	list := &collections.DoublyLinkedList[string]{}

	_ = list.Append("one")
	_ = list.Append("two")
	n := list.Append("three")
	n.Remove()

	next, stop := iter.Pull2(list.Iter())
	defer stop()

	i, x, ok := next()
	assert.Equal(t, 0, i)
	assert.Equal(t, "one", x)
	assert.True(t, ok)
	i, x, ok = next()
	assert.Equal(t, 1, i)
	assert.Equal(t, "two", x)
	assert.True(t, ok)
	_, _, ok = next()
	assert.False(t, ok)
}

func TestRemoveAfterRemove_Noop(t *testing.T) {
	list := &collections.DoublyLinkedList[int]{}

	_ = list.Append(0)
	n := list.Append(1)
	n.Remove()
	n.Remove()

	assert.Equal(t, list.Len(), 1)
}

func TestIter_StopsOnBreak(t *testing.T) {
	list := &collections.DoublyLinkedList[string]{}
	_ = list.Append("a")
	_ = list.Append("b")
	_ = list.Append("c")

	for _, x := range list.Iter() {
		if x == "b" {
			break
		}

		assert.NotEqual(t, "c", x)
	}
}
