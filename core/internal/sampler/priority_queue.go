package sampler

import (
	"container/heap"
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

// priorityQueueData represents the underlying data structure of the priority queue.
// It implements the heap.Interface interface.
type priorityQueueData[T comparable] []*Item[T]

// Compare the priority of the items at indices i and j,
// returning true if the item at i has lower priority than the item at j.
func (d priorityQueueData[T]) Less(i, j int) bool {
	return d[i].priority < d[j].priority
}

// Swap swaps the items at indices i and j.
func (d priorityQueueData[T]) Swap(i, j int) {
	d[i], d[j] = d[j], d[i]
}

// Push adds an item to the queue with the given value.
func (d *priorityQueueData[T]) Push(x any) {
	item := x.(*Item[T])
	*d = append(*d, item)
}

// Pop removes and returns the item with the highest priority from the queue.
func (d *priorityQueueData[T]) Pop() interface{} {
	old := *d
	n := len(old)
	item := old[n-1]
	old[n-1] = nil // avoid memory leak
	*d = old[0 : n-1]
	return item
}

// Len returns the number of elements in the queue.
func (d *priorityQueueData[T]) Len() int {
	return len(*d)
}

// PriorityQueue represents a queue of Items, ordered by their priority.
type PriorityQueue[T comparable] struct {
	data *priorityQueueData[T]
}

// NewPriorityQueue creates a new priority queue.
func NewPriorityQueue[T comparable]() *PriorityQueue[T] {
	pq := make(priorityQueueData[T], 0)
	return &PriorityQueue[T]{data: &pq}
}

func (pq PriorityQueue[T]) Push(item *Item[T]) {
	heap.Push(pq.data, item)
}

func (pq PriorityQueue[T]) Pop() *Item[T] {
	return heap.Pop(pq.data).(*Item[T])
}

func (pq PriorityQueue[T]) Len() int {
	return pq.data.Len()
}
