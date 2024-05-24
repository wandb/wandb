package pathtree

import (
	"fmt"
)

// TreeData is an internal representation for a nested key-value pair.
type TreeData = map[string]interface{}

// A key path determining a node in the tree.
type TreePath []string

// PathTree is used to represent a nested key-value pair object,
// such as Run config or summary.
type PathTree struct {
	// The underlying configuration tree.
	//
	// Nodes are strings and leaves are types supported by JSON,
	// such as primitives and lists.
	tree TreeData
}

// PathItem is a alternative representation of the item interface.
//
// The Value is a JSON string, which can be unmarshaled to any type.
type PathItem struct {
	Path  TreePath
	Value any
}

func New() *PathTree {
	return &PathTree{make(TreeData)}
}

func NewFrom(tree TreeData) *PathTree {
	return &PathTree{tree}
}

// Returns the underlying config tree.
//
// Provided temporarily as part of a refactor. Avoid using this, especially
// mutating it.
func (pt *PathTree) Tree() TreeData {
	return pt.tree
}

// Makes and returns a deep copy of the underlying tree.
func (pt *PathTree) CloneTree() (TreeData, error) {
	clone, err := deepCopy(pt.tree)
	if err != nil {
		return nil, err
	}
	return clone, nil
}

// Updates and/or removes values from the tree.
//
// Does a best-effort job to apply all changes. Errors are passed to `onError`
// and skipped.
func (pt *PathTree) ApplyUpdate(
	items []*PathItem,
	onError func(error),
) {
	for _, item := range items {
		if err := updateAtPath(pt.tree, item.Path, item.Value); err != nil {
			onError(err)
			continue
		}
	}
}

// Removes values from the tree.
func (pt *PathTree) ApplyRemove(
	items []*PathItem,
) {
	for _, item := range items {
		pt.removeAtPath(item.Path)
	}
}

// Removes the value at the path in the config tree.
func (pt *PathTree) removeAtPath(path TreePath) {
	prefix := path[:len(path)-1]
	key := path[len(path)-1]

	subtree := getSubtree(pt.tree, prefix)
	if subtree != nil {
		delete(subtree, key)
	}
}

// Uses the given subtree for keys that aren't already set.
func (pt *PathTree) AddUnsetKeysFromSubtree(
	tree TreeData,
	path TreePath,
) error {
	oldSubtree := getSubtree(tree, path)
	if oldSubtree == nil {
		return nil
	}

	newSubtree, err := GetOrMakeSubtree(pt.tree, path)
	if err != nil {
		return err
	}

	for key, value := range oldSubtree {
		if _, exists := newSubtree[key]; !exists {
			newSubtree[key] = value
		}
	}

	return nil
}

// Flattens the tree into a slice of leaves.
//
// Use this to get a list of all the leaves in the tree.
func (pt *PathTree) Flatten() []PathItem {
	return flatten(pt.tree, nil)
}

// Recursively flattens the tree into a slice of leaves.
//
// The order of the leaves is not guaranteed.
// The order of the leaves is determined by the order of the tree traversal.
// The tree traversal is depth-first but based on a map, so the order is not
// guaranteed.
func flatten(tree TreeData, prefix []string) []PathItem {
	var leaves []PathItem
	for key, value := range tree {
		switch value := value.(type) {
		case TreeData:
			leaves = append(leaves, flatten(value, append(prefix, key))...)
		default:
			leaves = append(leaves, PathItem{append(prefix, key), value})
		}
	}
	return leaves
}

// Sets the value at the path in the pathtree.
func updateAtPath(
	tree TreeData,
	path []string,
	value interface{},
) error {
	pathPrefix := path[:len(path)-1]
	key := path[len(path)-1]

	subtree, err := GetOrMakeSubtree(tree, pathPrefix)

	if err != nil {
		return err
	}

	subtree[key] = value
	return nil
}

// Returns the subtree at the path, or nil if it does not exist.
func getSubtree(
	tree TreeData,
	path TreePath,
) TreeData {
	for _, key := range path {
		node, ok := tree[key]
		if !ok {
			return nil
		}

		subtree, ok := node.(TreeData)
		if !ok {
			return nil
		}

		tree = subtree
	}

	return tree
}

// Returns the subtree at the path, creating it if necessary.
//
// Returns an error if there exists a non-map value at the path.
func GetOrMakeSubtree(
	tree TreeData,
	path TreePath,
) (TreeData, error) {
	for _, key := range path {
		node, exists := tree[key]
		if !exists {
			node = make(TreeData)
			tree[key] = node
		}

		subtree, ok := node.(TreeData)
		if !ok {
			return nil, fmt.Errorf(
				"config: value at path %v is type %T, not a map",
				path,
				node,
			)
		}

		tree = subtree
	}

	return tree, nil
}

// Returns a deep copy of the given tree.
//
// Slice values are copied by reference, which is fine for our use case.
func deepCopy(tree TreeData) (TreeData, error) {
	clone := make(TreeData)
	for key, value := range tree {
		switch value := value.(type) {
		case TreeData:
			innerClone, err := deepCopy(value)
			if err != nil {
				return nil, err
			}
			clone[key] = innerClone
		default:
			clone[key] = value
		}
	}
	return clone, nil
}
