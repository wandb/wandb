package pathtree

import (
	"fmt"

	"github.com/segmentio/encoding/json"
	"gopkg.in/yaml.v3"
)

// PathItem is a key-value pair with a path.
type PathItem struct {
	Path  []string
	Value string
}

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

type Format int

const (
	FormatYaml Format = iota
	FormatJson
)

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
func (pathTree *PathTree) Tree() TreeData {
	return pathTree.tree
}

// Makes and returns a deep copy of the underlying tree.
func (pathTree *PathTree) CloneTree() (TreeData, error) {
	clone, err := deepCopy(pathTree.tree)
	if err != nil {
		return nil, err
	}
	return clone, nil
}

// Updates and/or removes values from the tree.
//
// Does a best-effort job to apply all changes. Errors are passed to `onError`
// and skipped.
func (pathTree *PathTree) ApplyUpdate(
	items []*PathItem,
	onError func(error),
) {
	for _, item := range items {

		var value interface{}
		if err := json.Unmarshal(
			[]byte(item.Value),
			&value,
		); err != nil {
			onError(
				fmt.Errorf(
					"pathtree: failed to unmarshal JSON for config key %v: %v",
					item.Path,
					err,
				),
			)
			continue
		}

		if err := updateAtPath(pathTree.tree, item.Path, value); err != nil {
			onError(err)
			continue
		}
	}
}

func (pathTree *PathTree) ApplyRemove(
	items []*PathItem,
	onError func(error),
) {
	for _, item := range items {
		pathTree.removeAtPath(item.Path)
	}
}

// Serializes the object to send to the backend.
func (pathTree *PathTree) Serialize(format Format, formatValue func(any) any) ([]byte, error) {
	// A configuration dict in the format expected by the backend.
	serialized := make(map[string]any)
	for treeKey, treeValue := range pathTree.tree {
		serialized[treeKey] = formatValue(treeValue)
	}

	switch format {
	case FormatYaml:
		return yaml.Marshal(serialized)
	case FormatJson:
		return json.Marshal(serialized)
	}

	return nil, fmt.Errorf("config: unknown format: %v", format)
}

type Leaf struct {
	Key   []string
	Value any
}

// Flattens the tree into a slice of leaves.
//
// Use this to get a list of all the leaves in the tree.
func (pathTree *PathTree) Flatten() []Leaf {
	return flatten(pathTree.tree, nil)
}

// Recursively flattens the tree into a slice of leaves.
//
// The order of the leaves is not guaranteed.
// The order of the leaves is determined by the order of the tree traversal.
// The tree traversal is depth-first but based on a map, so the order is not
// guaranteed.
func flatten(tree TreeData, prefix []string) []Leaf {
	var leaves []Leaf
	for key, value := range tree {
		switch value := value.(type) {
		case TreeData:
			leaves = append(leaves, flatten(value, append(prefix, key))...)
		default:
			leaves = append(leaves, Leaf{append(prefix, key), value})
		}
	}
	return leaves
}

// Uses the given subtree for keys that aren't already set.
func (runConfig *PathTree) AddUnsetKeysFromSubtree(
	tree TreeData,
	path TreePath,
) error {
	oldSubtree := getSubtree(tree, path)
	if oldSubtree == nil {
		return nil
	}

	newSubtree, err := getOrMakeSubtree(runConfig.tree, path)
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

// Sets the value at the path in the config tree.
func updateAtPath(
	tree TreeData,
	path []string,
	value interface{},
) error {
	pathPrefix := path[:len(path)-1]
	key := path[len(path)-1]

	subtree, err := getOrMakeSubtree(tree, pathPrefix)

	if err != nil {
		return err
	}

	subtree[key] = value
	return nil
}

// Removes the value at the path in the config tree.
func (pathTree *PathTree) removeAtPath(path TreePath) {
	pathPrefix := path[:len(path)-1]
	key := path[len(path)-1]

	subtree := getSubtree(pathTree.tree, pathPrefix)
	if subtree != nil {
		delete(subtree, key)
	}
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
func getOrMakeSubtree(
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

type item interface {
	GetKey() string
	GetNestedKey() []string
	GetValueJson() string
}

func FromItem(item item) *PathItem {
	var key []string
	if len(item.GetNestedKey()) > 0 {
		key = item.GetNestedKey()
	} else {
		key = []string{item.GetKey()}
	}

	return &PathItem{
		Path:  key,
		Value: item.GetValueJson(),
	}
}
