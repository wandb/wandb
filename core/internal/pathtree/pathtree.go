package pathtree

import (
	"slices"

	"github.com/wandb/segmentio-encoding/json"
)

// TreePath is a list of strings mapping to a value.
type TreePath []string

// PathTree is a tree with a string at each non-leaf node.
//
// If the leaves are JSON values, then this is essentially a JSON object.
type PathTree struct {
	tree treeData
}

// treeData is an internal representation for a nested key-value pair.
//
// This is a map where values are either
//   - TreeData
//   - Any caller-provided type
type treeData map[string]any

// PathItem is the value at a leaf node and the path to that leaf.
type PathItem struct {
	Path  TreePath
	Value any
}

func New() *PathTree {
	return &PathTree{make(treeData)}
}

// CloneTree returns a nested-map representation of the tree.
//
// This always allocates a new map.
func (pt *PathTree) CloneTree() map[string]any {
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
func (pt *PathTree) Set(path TreePath, value any) {
	pathPrefix := path[:len(path)-1]
	key := path[len(path)-1]

	subtree := pt.getOrMakeSubtree(pathPrefix)
	subtree[key] = value
}

// SetSubtree recusrively replaces the subtree at the given path.
//
// The subtree is represented by a map from strings to subtrees or
// leaf values. This tree structure is copied to update the path
// tree.
func (pt *PathTree) SetSubtree(path TreePath, subtree map[string]any) {
	// Clone the path so that it is safe to append to it.
	path = slices.Clone(path)

	// TODO: this is inefficient---it has repeated getOrMakeSubtree calls
	for key, value := range subtree {
		switch x := value.(type) {
		case map[string]any:
			pt.SetSubtree(append(path, key), x)
		default:
			pt.Set(append(path, key), x)
		}
	}
}

// Remove deletes a node from the tree.
func (pt *PathTree) Remove(path TreePath) {
	if len(path) == 0 {
		return
	}

	prefix := path[:len(path)-1]
	key := path[len(path)-1]

	subtree := pt.getSubtree(prefix)
	if subtree == nil {
		return
	}

	delete(subtree, key)

	// Remove from parents to avoid keeping around empty maps.
	parentIdx := len(path) - 2
	for len(subtree) == 0 && parentIdx >= 0 {
		parent := pt.getSubtree(path[:parentIdx])
		delete(parent, path[parentIdx])

		parentIdx -= 1
		subtree = parent
	}
}

// IsEmpty returns whether the tree is empty.
func (pt *PathTree) IsEmpty() bool {
	return len(pt.tree) == 0
}

// GetLeaf returns the leaf value at path.
//
// Returns nil and false if the path doesn't lead to a leaf node.
// Otherwise, returns the leaf value and true.
func (pt *PathTree) GetLeaf(path TreePath) (any, bool) {
	prefix := path[:len(path)-1]
	key := path[len(path)-1]

	subtree := pt.getSubtree(prefix)
	if subtree == nil {
		return nil, false
	}

	value, exists := subtree[key]
	if !exists {
		return nil, false
	}

	switch value.(type) {
	case treeData:
		return nil, false
	default:
		return value, true
	}
}

// HasNode returns whether a node exists at the path.
func (pt *PathTree) HasNode(path TreePath) bool {
	prefix := path[:len(path)-1]
	key := path[len(path)-1]

	subtree := pt.getSubtree(prefix)
	if subtree == nil {
		return false
	}

	_, exists := subtree[key]
	return exists
}

// ForEachLeaf runs a callback on each leaf value in the tree.
//
// The order is unspecified and non-deterministic.
//
// The callback returns true to continue and false to stop iteration early.
func (pt *PathTree) ForEachLeaf(fn func(path TreePath, value any) bool) {
	_ = forEachLeaf(pt.tree, nil, fn)
}

func forEachLeaf(
	tree treeData,
	prefix []string,
	fn func(path TreePath, value any) bool,
) bool {
	for key, value := range tree {
		// We must clone each time because the callback may store
		// a reference to the slice we create.
		path := append(slices.Clone(prefix), key)

		switch x := value.(type) {
		case treeData:
			if !forEachLeaf(x, path, fn) {
				return false
			}

		default:
			if !fn(path, value) {
				return false
			}
		}
	}

	return true
}

// Flatten returns all the leaves of the tree.
//
// The order is nondeterministic.
func (pt *PathTree) Flatten() []PathItem {
	return flatten(pt.tree, nil)
}

// flatten returns the leaves of the tree, prepending a prefix to paths.
func flatten(tree treeData, prefix []string) []PathItem {
	var leaves []PathItem
	for key, value := range tree {
		switch value := value.(type) {
		case treeData:
			leaves = append(leaves, flatten(value, append(prefix, key))...)
		default:
			leaves = append(leaves, PathItem{append(prefix, key), value})
		}
	}
	return leaves
}

// ToExtendedJSON encodes the tree as an extension of JSON that supports NaN
// and +-Infinity.
//
// Values must be JSON-encodable.
func (pt *PathTree) ToExtendedJSON() ([]byte, error) {
	return json.Marshal(pt.tree)
}

// getSubtree returns the subtree at the path or nil if the path doesn't lead
// to a non-leaf node.
func (pt *PathTree) getSubtree(path TreePath) treeData {
	tree := pt.tree

	for _, key := range path {
		node, ok := tree[key]
		if !ok {
			return nil
		}

		subtree, ok := node.(treeData)
		if !ok {
			return nil
		}

		tree = subtree
	}

	return tree
}

// getOrMakeSubtree returns the subtree at the path, creating it if necessary.
//
// Any leaf nodes along the path get overwritten.
func (pt *PathTree) getOrMakeSubtree(path TreePath) treeData {
	tree := pt.tree

	for _, key := range path {
		node, exists := tree[key]
		if !exists {
			subtree := make(treeData)
			tree[key] = subtree
			tree = subtree
			continue
		}

		subtree, ok := node.(treeData)
		if !ok {
			subtree = make(treeData)
			tree[key] = subtree
		}

		tree = subtree
	}

	return tree
}

// Returns a deep copy of the given tree.
//
// Slice values are copied by reference, which is fine for our use case.
func toNestedMaps(tree treeData) map[string]any {
	clone := make(map[string]any)
	for key, value := range tree {
		switch value := value.(type) {
		case treeData:
			clone[key] = toNestedMaps(value)
		default:
			clone[key] = value
		}
	}
	return clone
}
