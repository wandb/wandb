package collections

import "iter"

// DoublyLinkedList is a linked list where each node has a pointer to
// the previous and next nodes.
//
// The only reason to use this rather than a slice is if nodes need to
// be removed from the list in an unpredictable order, as Remove()
// is O(1).
type DoublyLinkedList[T any] struct {
	// first is the oldest node in the list that hasn't been removed.
	//
	// It is kept for iterating over the list in order.
	first *DoublyLinkedListNode[T]

	// last is the newest node in the list that hasn't been removed.
	//
	// It is kept for appending to the list.
	last *DoublyLinkedListNode[T]

	// length is the number of nodes in the list.
	length int
}

// Append adds the item to the end of the list and returns its node.
func (list *DoublyLinkedList[T]) Append(t T) *DoublyLinkedListNode[T] {
	node := &DoublyLinkedListNode[T]{Value: t, list: list}

	if list.last == nil {
		list.first = node
		list.last = node
	} else {
		list.last.next = node
		node.prev = list.last

		list.last = node
	}

	list.length++

	return node
}

// Len returns the number of items in the list.
func (list *DoublyLinkedList[T]) Len() int {
	return list.length
}

// Iter iterates over the list in append order.
//
// This is intended to be used with for-range syntax in Go 1.23.
func (list *DoublyLinkedList[T]) Iter() iter.Seq2[int, T] {
	return func(yield func(int, T) bool) {
		i := 0
		node := list.first
		for node != nil {
			if !yield(i, node.Value) {
				return
			}

			node = node.next
			i++
		}
	}
}

// DoublyLinkedListNode is a node in a doubly linked list.
type DoublyLinkedListNode[T any] struct {
	Value T                        // the value at this point in the list
	list  *DoublyLinkedList[T]     // the list itself
	prev  *DoublyLinkedListNode[T] // the previous node (if any)
	next  *DoublyLinkedListNode[T] // the next node (if any)
}

// Remove removes the node from the list.
//
// Since this modifies the list, it is not safe to use it concurrently
// with appending or iterating over the list.
func (node *DoublyLinkedListNode[T]) Remove() {
	if node.list == nil {
		return
	}

	// Update sibling nodes.
	if node.prev != nil {
		node.prev.next = node.next
	}
	if node.next != nil {
		node.next.prev = node.prev
	}

	// Update first and last pointers in the source list.
	if node.list.first == node {
		node.list.first = node.next
	}
	if node.list.last == node {
		node.list.last = node.prev
	}

	node.list.length--
	node.list = nil
}
