package sparselist

import (
	"iter"
	"maps"
	"math"
	"slices"
)

// SparseList is a list where many indices are not set.
//
// A `SparseList[T]` is like `(int, []*T)` but uses less memory when
// many values are nil and can perform some operations more efficiently. The
// extra 'int' is there because a `SparseList` can have negative indices.
//
// The zero value is an empty list.
//
// A nil SparseList is like a nil map: all getter methods treat it like an
// empty SparseList, and all mutating methods panic.
type SparseList[T any] struct {
	items        map[int]T
	firstIndex   int
	lastIndex    int
	boundsCached bool
}

// Len returns the number of indices in the list that are set.
func (l *SparseList[T]) Len() int {
	if l == nil {
		return 0
	}

	return len(l.items)
}

// FirstIndex is the smallest index that is set, if Len > 0.
func (l *SparseList[T]) FirstIndex() int {
	if l == nil {
		return 0
	}

	if !l.boundsCached {
		l.recomputeBounds()
	}

	return l.firstIndex
}

// LastIndex is the largest index that is set, if Len > 0.
func (l *SparseList[T]) LastIndex() int {
	if l == nil {
		return 0
	}

	if !l.boundsCached {
		l.recomputeBounds()
	}

	return l.lastIndex
}

// recomputeBounds recomputes firstIndex and lastIndex.
func (l *SparseList[T]) recomputeBounds() {
	if len(l.items) == 0 {
		return
	}

	l.firstIndex = math.MaxInt
	l.lastIndex = math.MinInt

	for i := range l.items {
		l.firstIndex = min(i, l.firstIndex)
		l.lastIndex = max(i, l.lastIndex)
	}

	l.boundsCached = true
}

// Put inserts an item into the list.
func (l *SparseList[T]) Put(index int, item T) {
	if len(l.items) == 0 {
		l.items = map[int]T{index: item}
		l.firstIndex = index
		l.lastIndex = index
		l.boundsCached = true
	} else {
		l.items[index] = item

		if l.boundsCached {
			l.firstIndex = min(l.firstIndex, index)
			l.lastIndex = max(l.lastIndex, index)
		}
	}
}

// Get returns an item at an index in the list.
//
// The second return value indicates whether there was anything at the index.
func (l *SparseList[T]) Get(index int) (T, bool) {
	if l == nil || len(l.items) == 0 {
		return *new(T), false
	}

	item, ok := l.items[index]
	return item, ok
}

// GetOrZero returns an item at an index in the list, or the zero value.
func (l *SparseList[T]) GetOrZero(index int) T {
	x, _ := l.Get(index)
	return x
}

// Delete clears an index in the list.
//
// Viewing `SparseList[T]` as `[]*T`, this is equivalent to replacing
// the index by `nil`.
func (l *SparseList[T]) Delete(index int) {
	delete(l.items, index)

	if index == l.firstIndex || index == l.lastIndex {
		l.boundsCached = false
	}
}

// Update overwrites the data in this list by the other list.
func (l *SparseList[T]) Update(other *SparseList[T]) {
	if other.Len() == 0 {
		return
	}

	if l.items == nil {
		l.items = make(map[int]T)
	}

	maps.Copy(l.items, other.items)
	l.boundsCached = false
}

// FirstRun returns an iterator over the first run of consecutive values
// in the list.
//
// It is valid to modify the list while iterating through this.
func (l *SparseList[T]) FirstRun() iter.Seq2[int, T] {
	return func(yield func(idx int, value T) bool) {
		if l.Len() == 0 {
			return
		}

		for i := l.FirstIndex(); i <= l.LastIndex(); i++ {
			value, ok := l.Get(i)
			if !ok || !yield(i, value) {
				return
			}
		}
	}
}

// FirstRunValues is like FirstRun but without indices.
func (l *SparseList[T]) FirstRunValues() iter.Seq[T] {
	return func(yield func(value T) bool) {
		for _, value := range l.FirstRun() {
			if !yield(value) {
				return
			}
		}
	}
}

// ForEach invokes a callback on each value in the list.
func (l *SparseList[T]) ForEach(fn func(int, T)) {
	if l == nil {
		return
	}

	for i, x := range l.items {
		fn(i, x)
	}
}

// Map returns a new list by applying a transformation to each element.
func Map[T, U any](list *SparseList[T], fn func(T) U) *SparseList[U] {
	result := &SparseList[U]{}

	list.ForEach(func(i int, x T) {
		result.Put(i, fn(x))
	})

	return result
}

// Run is a sequence of consecutive values in a sparse list.
type Run[T any] struct {
	// Start is the index in the list where the run starts.
	Start int

	// Items is a slice of values.
	Items []T
}

// ToMap returns this list as a map from indices to values.
func (l *SparseList[T]) ToMap() map[int]T {
	if l == nil {
		return nil
	}

	return maps.Clone(l.items)
}

// ToRuns returns the runs of consecutive values in the list.
func (l *SparseList[T]) ToRuns() []Run[T] {
	if l == nil {
		return nil
	}

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
