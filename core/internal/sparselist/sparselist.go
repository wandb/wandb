package sparselist

import (
	"maps"
	"slices"
)

// SparseList is a list where many indices are not set.
//
// A `SparseList[T]` is isomorphic to `(int, []*T)` but uses less memory when
// many values are nil and can perform some operations more efficiently. The
// extra 'int' is there because a `SparseList` can have negative indices.
//
// The zero value is an empty list.
type SparseList[T any] struct {
	items map[int]T
}

// Len returns the number of indices in the list that are set.
func (l *SparseList[T]) Len() int {
	return len(l.items)
}

// Put inserts an item into the list.
func (l *SparseList[T]) Put(index int, item T) {
	if l.items == nil {
		l.items = make(map[int]T)
	}

	l.items[index] = item
}

// Delete clears an index in the list.
//
// Viewing `SparseList[T]` as `[]*T`, this is equivalent to replacing
// the index by `nil`.
func (l *SparseList[T]) Delete(index int) {
	delete(l.items, index)
}

// Update overwrites the data in this list by the other list.
func (l *SparseList[T]) Update(other SparseList[T]) {
	maps.Copy(l.items, other.items)
}

// Run is a sequence of consecutive values in a sparse list.
type Run[T any] struct {
	// Start is the index in the list where the run starts.
	Start int

	// Items is a slice of values.
	Items []T
}

// ToRuns returns the runs of consecutive values in the list.
func (l *SparseList[T]) ToRuns() []Run[T] {
	indices := make([]int, 0, len(l.items))
	for listIdx := range l.items {
		indices = append(indices, listIdx)
	}
	slices.Sort(indices)

	if len(indices) == 0 {
		return make([]Run[T], 0)
	}

	runs := []Run[T]{
		{
			Start: indices[0],
			Items: []T{l.items[indices[0]]},
		},
	}

	for i, listIdx := range indices[1:] {
		prevListIdx := indices[i]
		item := l.items[listIdx]

		if listIdx == prevListIdx+1 {
			// We're still in the same run.
			prevRun := &runs[len(runs)-1]
			prevRun.Items = append(prevRun.Items, item)
		} else {
			// We're starting a new run.
			runs = append(runs, Run[T]{
				Start: listIdx,
				Items: []T{item},
			})
		}
	}

	return runs
}
