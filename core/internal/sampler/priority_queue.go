package sampler

import (
	"fmt"
)

// Item represents a single element in the priority queue.
type Item[T comparable] struct {

	// value is the value of the item
	value T

	// priority is the priority of the item
	priority float64

	// index is the order in which the item was added
	index int
}

// String returns the string representation of the item's value.
func (item Item[T]) String() string {
	return fmt.Sprintf("%v", item.value)
}

// PriorityQueue represents a queue of Items, ordered by their priority.
type PriorityQueue[T comparable] []*Item[T]

// Len returns the number of elements in the queue.
func (pq PriorityQueue[T]) Len() int {
	return len(pq)
}

// Compare the priority of the items at indices i and j,
// returning true if the item at i has lower priority than the item at j.
func (pq PriorityQueue[T]) Less(i, j int) bool {
	return pq[i].priority < pq[j].priority
}

// Swap swaps the items at indices i and j.
func (pq PriorityQueue[T]) Swap(i, j int) {
	pq[i], pq[j] = pq[j], pq[i]
}

// Push adds an item to the queue with the given value.
func (pq *PriorityQueue[T]) Push(x any) {
	item := x.(*Item[T])
	*pq = append(*pq, item)
}

// Pop removes and returns the item with the highest priority from the queue.
func (pq *PriorityQueue[T]) Pop() interface{} {
	old := *pq
	n := len(old)
	item := old[n-1]
	old[n-1] = nil // avoid memory leak
	*pq = old[0 : n-1]
	return item
}
