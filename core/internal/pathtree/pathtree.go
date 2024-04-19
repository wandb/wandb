package pathtree

import (
	"fmt"

	"github.com/segmentio/encoding/json"
	"gopkg.in/yaml.v3"
)

// Generic item which works with config, summary, and history
type item interface {
	GetKey() string
	GetNestedKey() []string
	GetValueJson() string
}

// TreeData is an internal representation for a nested key-value pair.
type TreeData = map[string]interface{}

// A key path determining a node in the tree.
type TreePath []string

// PathTree is used to represent a nested key-value pair object,
// such as Run config or summary.
type PathTree[I item] struct {
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

func New[I item]() *PathTree[I] {
	return &PathTree[I]{make(TreeData)}
}

func NewFrom[I item](tree TreeData) *PathTree[I] {
	return &PathTree[I]{tree}
}

// Returns the underlying config tree.
//
// Provided temporarily as part of a refactor. Avoid using this, especially
// mutating it.
func (pathTree *PathTree[I]) Tree() TreeData {
	return pathTree.tree
}

// Makes and returns a deep copy of the underlying tree.
func (pathTree *PathTree[I]) CloneTree() (TreeData, error) {
	clone, err := DeepCopy(pathTree.tree)
	if err != nil {
		return nil, err
	}
	return clone, nil
}

// Updates and/or removes values from the tree.
//
// Does a best-effort job to apply all changes. Errors are passed to `onError`
// and skipped.
func (pathTree *PathTree[I]) ApplyUpdate(
	update []I,
	onError func(error),
) {
	for _, val := range update {
		path := keyPath(val)

		var value interface{}
		if err := json.Unmarshal(
			[]byte(val.GetValueJson()),
			&value,
		); err != nil {
			onError(
				fmt.Errorf(
					"config: failed to unmarshal JSON for config key %v: %v",
					path,
					err,
				),
			)
			continue
		}

		if err := updateAtPath(pathTree.tree, path, value); err != nil {
			onError(err)
			continue
		}
	}
}

func (pathTree *PathTree[I]) ApplyRemove(
	remove []I,
	onError func(error),
) {
	for _, val := range remove {
		pathTree.removeAtPath(keyPath(val))
	}
}

// Serializes the object to send to the backend.
func (pathTree *PathTree[I]) Serialize(format Format) ([]byte, error) {
	// A configuration dict in the format expected by the backend.
	serialized := make(map[string]map[string]interface{})
	for treeKey, treeValue := range pathTree.tree {
		serialized[treeKey] = map[string]interface{}{
			"value": treeValue,
		}
	}

	switch format {
	case FormatYaml:
		return yaml.Marshal(serialized)
	case FormatJson:
		return json.Marshal(serialized)
	}

	return nil, fmt.Errorf("config: unknown format: %v", format)
}

// Uses the given subtree for keys that aren't already set.
func (runConfig *PathTree[I]) AddUnsetKeysFromSubtree(
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
func (pathTree *PathTree[I]) removeAtPath(path TreePath) {
	pathPrefix := path[:len(path)-1]
	key := path[len(path)-1]

	subtree := getSubtree(pathTree.tree, pathPrefix)
	if subtree != nil {
		delete(subtree, key)
	}
}

// Returns the key path referenced by the item.
func keyPath(item item) TreePath {
	if len(item.GetNestedKey()) > 0 {
		return TreePath(item.GetNestedKey())
	} else {
		return TreePath{item.GetKey()}
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
func DeepCopy(tree TreeData) (TreeData, error) {
	clone := make(TreeData)
	for key, value := range tree {
		switch value := value.(type) {
		case TreeData:
			innerClone, err := DeepCopy(value)
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
