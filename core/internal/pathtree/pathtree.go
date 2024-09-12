package pathtree

import (
	"github.com/wandb/simplejsonext"
)

// TreePath is the list of node labels along the path from the root
// of a PathTree to a node.
type TreePath struct {
	// labels is a non-empty slice defining the path.
	labels []string
}

// PathOf creates a TreePath from a list of labels.
func PathOf(first string, rest ...string) TreePath {
	labels := make([]string, 0, 1+len(rest))
	labels = append(labels, first)
	labels = append(labels, rest...)
	return TreePath{labels}
}

// PathWithPrefix creates a TreePath from a prefix and an end label.
func PathWithPrefix(prefix []string, key string) TreePath {
	labels := make([]string, 0, len(prefix)+1)
	labels = append(labels, prefix...)
	labels = append(labels, key)
	return TreePath{labels}
}

// With returns a TreePath extended by the additional labels.
func (p TreePath) With(more ...string) TreePath {
	if len(more) == 0 {
		return p
	}

	labels := make([]string, 0, len(p.labels)+len(more))
	labels = append(labels, p.labels...)
	labels = append(labels, more...)
	return TreePath{labels}
}

// Parent returns this path without the last component.
//
// Returns true as the second value if the path has a parent,
// and false otherwise. If this returns false, the resulting
// TreePath is invalid and must not be used.
func (p TreePath) Parent() (TreePath, bool) {
	if len(p.labels) <= 1 {
		return TreePath{}, false
	}

	return TreePath{p.labels[:len(p.labels)-1]}, true
}

// Len returns the number of labels in the path, which is always >0.
func (p TreePath) Len() int {
	return len(p.labels)
}

// Labels returns the path as a list of labels.
//
// The returned slice must not be modified.
func (p TreePath) Labels() []string {
	return p.labels
}

// Prefix returns all but the last label in the path.
//
// The returned slice must not be modified.
func (p TreePath) Prefix() []string {
	return p.labels[:len(p.labels)-1]
}

// End returns the last label in the path.
func (p TreePath) End() string {
	return p.labels[len(p.labels)-1]
}

// PathTree is a tree with a string at each non-leaf node.
//
// If the leaves are JSON values, then this is essentially a JSON object.
type PathTree[T any] struct {
	tree treeData[T]
}

// treeData is an internal representation for a nested key-value pair.
//
// This is a map where values are either
//   - TreeData
//   - Any caller-provided type
type treeData[T any] map[string]treeNode[T]

type treeNode[T any] struct {
	// Subtree is the subtree at the node.
	//
	// If this is nil, then this is a leaf node, even if Leaf is nil.
	Subtree treeData[T]

	// Leaf is the leaf value if this is a leaf node.
	Leaf T
}

// IsLeaf reports whether the node is a leaf.
func (n *treeNode[T]) IsLeaf() bool {
	return n.Subtree == nil
}

// PathItem is the value at a leaf node and the path to that leaf.
type PathItem struct {
	Path  TreePath
	Value any
}

func New[T any]() *PathTree[T] {
	return &PathTree[T]{make(treeData[T])}
}

// CloneTree returns a nested-map representation of the tree.
//
// This always allocates a new map.
func (pt *PathTree[T]) CloneTree() map[string]any {
	return toNestedMaps(pt.tree)
}

// Set changes the value of the leaf node at the given path.
//
// Map values do not affect the tree structure---see SetSubtree instead.
//
// If the path doesn't refer to a node in the tree, nodes are inserted
// and a new leaf is created.
//
// If path refers to a non-leaf node, that node is replaced by a leaf
// and the subtree is discarded.
func (pt *PathTree[T]) Set(path TreePath, value T) {
	subtree := pt.getOrMakeSubtree(path.Prefix())
	subtree[path.End()] = treeNode[T]{Leaf: value}
}

// SetSubtree recursively replaces the subtree at the given path.
//
// The subtree is represented by a map from strings to subtrees or
// leaf values. This tree structure is copied to update the path
// tree.
func SetSubtree(pt *PathTree[any], path TreePath, subtree map[string]any) {
	// TODO: this is inefficient---it has repeated getOrMakeSubtree calls
	for key, value := range subtree {
		switch x := value.(type) {
		case map[string]any:
			SetSubtree(pt, path.With(key), x)
		default:
			pt.Set(path.With(key), x)
		}
	}
}

// Remove deletes a node from the tree.
func (pt *PathTree[T]) Remove(path TreePath) {
	subtree := pt.getSubtree(path.Prefix())
	if subtree == nil {
		return
	}

	delete(subtree, path.End())

	// Remove from parents to avoid keeping around empty maps.
	for len(subtree) == 0 {
		var ok bool
		path, ok = path.Parent()
		if !ok {
			return
		}

		subtree = pt.getSubtree(path.Prefix())
		delete(subtree, path.End())
	}
}

// IsEmpty returns whether the tree is empty.
func (pt *PathTree[T]) IsEmpty() bool {
	return len(pt.tree) == 0
}

// GetLeaf returns the leaf value at path.
//
// Returns the zero value and false if the path doesn't lead to a leaf node.
// Otherwise, returns the leaf value and true.
func (pt *PathTree[T]) GetLeaf(path TreePath) (T, bool) {
	subtree := pt.getSubtree(path.Prefix())
	if subtree == nil {
		return *new(T), false
	}

	value, exists := subtree[path.End()]
	if !exists || !value.IsLeaf() {
		return *new(T), false
	}

	return value.Leaf, true
}

// GetOrMakeLeaf returns the leaf value at path, creating one if necessary.
func (pt *PathTree[T]) GetOrMakeLeaf(
	path TreePath,
	makeDefault func() T,
) T {
	subtree := pt.getOrMakeSubtree(path.Prefix())

	node, exists := subtree[path.End()]
	if !exists || !node.IsLeaf() {
		node = treeNode[T]{Leaf: makeDefault()}
		subtree[path.End()] = node
	}

	return node.Leaf
}

// HasNode returns whether a node exists at the path.
func (pt *PathTree[T]) HasNode(path TreePath) bool {
	subtree := pt.getSubtree(path.Prefix())
	if subtree == nil {
		return false
	}

	_, exists := subtree[path.End()]
	return exists
}

// ForEachLeaf runs a callback on each leaf value in the tree.
//
// The order is unspecified and non-deterministic.
//
// The callback returns true to continue and false to stop iteration early.
func (pt *PathTree[T]) ForEachLeaf(fn func(path TreePath, value T) bool) {
	_ = forEachLeaf(pt.tree, nil, fn)
}

func forEachLeaf[T any](
	tree treeData[T],
	prefix []string,
	fn func(path TreePath, value T) bool,
) bool {
	for key, node := range tree {
		path := PathWithPrefix(prefix, key)

		switch {
		case node.IsLeaf():
			if !fn(path, node.Leaf) {
				return false
			}
		default:
			if !forEachLeaf(node.Subtree, path.Labels(), fn) {
				return false
			}
		}
	}

	return true
}

// Flatten returns all the leaves of the tree.
//
// The order is nondeterministic.
func (pt *PathTree[T]) Flatten() []PathItem {
	return flatten(pt.tree, nil)
}

// flatten returns the leaves of the tree, prepending a prefix to paths.
func flatten[T any](tree treeData[T], prefix []string) []PathItem {
	var leaves []PathItem
	for key, node := range tree {
		path := PathWithPrefix(prefix, key)

		switch {
		case node.IsLeaf():
			leaves = append(leaves, PathItem{path, node.Leaf})
		default:
			leaves = append(leaves, flatten(node.Subtree, path.Labels())...)
		}
	}
	return leaves
}

// ToExtendedJSON encodes the tree as an extension of JSON that supports NaN
// and +-Infinity.
//
// Values must be JSON-encodable.
func (pt *PathTree[T]) ToExtendedJSON() ([]byte, error) {
	return simplejsonext.Marshal(toNestedMaps(pt.tree))
}

// getSubtree returns the subtree at the path or nil if the path doesn't lead
// to a non-leaf node.
func (pt *PathTree[T]) getSubtree(path []string) treeData[T] {
	tree := pt.tree

	for _, key := range path {
		node, ok := tree[key]
		if !ok {
			return nil
		}

		if node.Subtree == nil {
			return nil
		}

		tree = node.Subtree
	}

	return tree
}

// getOrMakeSubtree returns the subtree at the path, creating it if necessary.
//
// Any leaf nodes along the path get overwritten.
func (pt *PathTree[T]) getOrMakeSubtree(path []string) treeData[T] {
	tree := pt.tree

	for _, key := range path {
		node, exists := tree[key]

		if !exists || node.IsLeaf() {
			node = treeNode[T]{Subtree: make(treeData[T])}
			tree[key] = node
		}

		tree = node.Subtree
	}

	return tree
}

// Returns a deep copy of the given tree.
//
// Slice values are copied by reference, which is fine for our use case.
func toNestedMaps[T any](tree treeData[T]) map[string]any {
	clone := make(map[string]any)
	for key, node := range tree {
		if node.IsLeaf() {
			clone[key] = node.Leaf
		} else {
			clone[key] = toNestedMaps(node.Subtree)
		}
	}
	return clone
}
