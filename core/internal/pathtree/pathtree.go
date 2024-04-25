package pathtree

import (
	"fmt"

	"github.com/segmentio/encoding/json"
	// TODO: use simplejsonext for now until we replace the usage of json with
	// protocol buffer and proto json marshaler
	jsonext "github.com/wandb/simplejsonext"
	"gopkg.in/yaml.v3"
)

// A type alias for any value that is passed from the client.
//
// It included HistoryItem, SummaryItem, ConfigItem, etc.
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
	FormatJsonExt
)

// PathItem is a alternative representation of the item interface.
//
// The Value is a JSON string, which can be unmarshaled to any type.
type PathItem struct {
	Path  TreePath
	Value string
}

// Leaf is a the leaf node in the tree.
//
// The Value could be any primitive type, list.
type Leaf struct {
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
//
// TODO: ideally we would not need to pass the format here, and instead
// receive the values as unmarshaled objects and marshal them when needed.
func (pt *PathTree) ApplyUpdate(
	items []*PathItem,
	onError func(error),
	format Format,
) {
	for _, item := range items {
		var (
			value interface{}
			err   error
		)
		if value, err = unmarshal([]byte(item.Value),
			format,
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

		if err := updateAtPath(pt.tree, item.Path, value); err != nil {
			onError(err)
			continue
		}
	}
}

// Removes values from the tree.
func (pt *PathTree) ApplyRemove(
	items []*PathItem,
	onError func(error),
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

	newSubtree, err := getOrMakeSubtree(pt.tree, path)
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

// Serializes the object to send to the backend.
func (pt *PathTree) Serialize(
	format Format,
	processValue func(any) any,
) ([]byte, error) {
	// A configuration dict in the format expected by the backend.
	value := make(map[string]any)
	for treeKey, treeValue := range pt.tree {
		if processValue == nil {
			value[treeKey] = treeValue
		} else {
			value[treeKey] = processValue(treeValue)
		}
	}
	return marshal(value, format)
}

// FlattenAndSerialize flattens the tree into a slice of leaves and marshals the values.
//
// Use this to get a list of all the leaves in the tree with their values
// marshaled.
//
// TODO: Ideally in the future we would not need to marshal the values here.
// and postpone marshaling when the values are beening sent to the backend.
func (pt *PathTree) FlattenAndSerialize(format Format) ([]PathItem, error) {

	if !(format == FormatYaml || format == FormatJson || format == FormatJsonExt) {
		return nil, fmt.Errorf("pathtree: unknown format %v", format)
	}

	leaves := flatten(pt.tree, nil)

	items := make([]PathItem, 0, len(leaves))
	for _, leaf := range leaves {
		value, err := marshal(leaf.Value, format)
		if err != nil {
			return nil, fmt.Errorf(
				"pathtree: failed to marshal value for path %v: %v",
				leaf.Path,
				err,
			)
		}
		items = append(items, PathItem{leaf.Path, string(value)})
	}
	return items, nil
}

// Flattens the tree into a slice of leaves.
//
// Use this to get a list of all the leaves in the tree.
func (pt *PathTree) Flatten() []Leaf {
	return flatten(pt.tree, nil)
}

// Converts an item to a PathItem.
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

// Unmarshals the value from the given format.
//
// Returns an error if the format is unknown.
// Supported formats are FormatYaml, FormatJson, and FormatJsonExt.
// FormatJsonExt is a custom JSON format that supports Infinity and NaN.
func unmarshal(b []byte, format Format) (interface{}, error) {
	switch format {
	case FormatYaml:
		var value interface{}
		err := yaml.Unmarshal(b, &value)
		return value, err
	case FormatJson:
		var value interface{}
		err := json.Unmarshal(b, &value)
		return value, err
	case FormatJsonExt:
		return jsonext.Unmarshal(b)
	default:
		return nil, fmt.Errorf("pathtree: unknown format %v", format)
	}
}

// Marshals the value to the given format.
//
// Returns an error if the format is unknown.
// Supported formats are FormatYaml, FormatJson, and FormatJsonExt.
// FormatJsonExt is a custom JSON format that supports Infinity and NaN.
func marshal(v interface{}, format Format) ([]byte, error) {
	switch format {
	case FormatYaml:
		return yaml.Marshal(v)
	case FormatJson:
		return json.Marshal(v)
	case FormatJsonExt:
		return jsonext.Marshal(v)
	default:
		return nil, fmt.Errorf("pathtree: unknown format %v", format)
	}
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
