package pathtree

// TreeData is an internal representation for a nested key-value pair.
//
// This is a map where values are either
//   - TreeData
//   - Any caller-provided type
//
// TODO: Remove this---it should not be exported.
type TreeData = map[string]any

// TreePath is a list of strings mapping to a value.
type TreePath []string

// PathTree is a tree with a string at each non-leaf node.
type PathTree struct {
	// The underlying configuration tree.
	tree TreeData
}

// PathItem is the value at a leaf node and the path to that leaf.
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

// Returns the underlying tree.
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

// Set changes the value of the leaf node at the given path.
//
// If the path doesn't refer to a node in the tree, nodes are inserted
// and a new leaf is created.
//
// If path refers to a non-leaf node, that node is replaced by a leaf
// and the subtree is discarded.
func (pt *PathTree) Set(path TreePath, value any) {
	pathPrefix := path[:len(path)-1]
	key := path[len(path)-1]

	subtree := getOrMakeSubtree(pt.tree, pathPrefix)
	subtree[key] = value
}

// Remove deletes a node from the tree.
func (pt *PathTree) Remove(path TreePath) {
	prefix := path[:len(path)-1]
	key := path[len(path)-1]

	// TODO: This can leave empty trees around.
	subtree := getSubtree(pt.tree, prefix)
	if subtree != nil {
		delete(subtree, key)
	}
}

// GetLeaf returns the leaf value at path.
//
// Returns nil and false if the path doesn't lead to a leaf node.
// Otherwise, returns the leaf value and true.
func (pt *PathTree) GetLeaf(path TreePath) (any, bool) {
	prefix := path[:len(path)-1]
	key := path[len(path)-1]

	subtree := getSubtree(pt.tree, prefix)
	if subtree == nil {
		return nil, false
	}

	value, exists := subtree[key]
	if !exists {
		return nil, false
	}

	switch value.(type) {
	case TreeData:
		return nil, false
	default:
		return value, true
	}
}

// AddUnsetKeysFromSubtree uses the given subtree for keys that aren't
// already set.
func (pt *PathTree) AddUnsetKeysFromSubtree(
	tree TreeData,
	path TreePath,
) {
	oldSubtree := getSubtree(tree, path)
	if oldSubtree == nil {
		return
	}

	newSubtree := getOrMakeSubtree(pt.tree, path)

	for key, value := range oldSubtree {
		if _, exists := newSubtree[key]; !exists {
			newSubtree[key] = value
		}
	}
}

// Flatten returns all the leaves of the tree.
//
// The order is nondeterministic.
func (pt *PathTree) Flatten() []PathItem {
	return flatten(pt.tree, nil)
}

// flatten returns the leaves of the tree, prepending a prefix to paths.
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

// getSubtree returns the subtree at the path or nil if the path doesn't lead
// to a non-leaf node.
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

// getOrMakeSubtree returns the subtree at the path, creating it if necessary.
//
// Any leaf nodes along the path get overwritten.
func getOrMakeSubtree(
	tree TreeData,
	path TreePath,
) TreeData {
	for _, key := range path {
		node, exists := tree[key]
		if !exists {
			subtree := make(TreeData)
			tree[key] = subtree
			tree = subtree
			continue
		}

		subtree, ok := node.(TreeData)
		if !ok {
			subtree = make(TreeData)
			tree[key] = subtree
		}

		tree = subtree
	}

	return tree
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
