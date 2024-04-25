package pathtree_test

import (
	"encoding/json"
	"math"
	"reflect"
	"sort"
	"strings"
	"testing"

	"github.com/wandb/wandb/core/internal/pathtree"
	"gopkg.in/yaml.v3"
)

// Mock item for testing
type MockItem struct {
	key       string
	nestedKey []string
	valueJson string
}

func (mi MockItem) GetKey() string {
	return mi.key
}

func (mi MockItem) GetNestedKey() []string {
	return mi.nestedKey
}

func (mi MockItem) GetValueJson() string {
	return mi.valueJson
}

func TestNewPathTree(t *testing.T) {
	pt := pathtree.New()
	if pt == nil {
		t.Error("NewPathTree() should not return nil")
	}
	if pt.Tree() == nil {
		t.Error("NewPathTree() tree should not be nil")
	}
}

func TestNewPathTreeFrom(t *testing.T) {
	treeData := pathtree.TreeData{
		"config": map[string]interface{}{
			"setting1": "value1",
		},
	}
	pt := pathtree.NewFrom(treeData)
	if pt == nil {
		t.Error("NewPathTreeFrom() should not return nil")
	}
	if pt.Tree() == nil {
		t.Error("NewPathTreeFrom() tree should not be nil")
	}
	if !reflect.DeepEqual(pt.Tree(), treeData) {
		t.Errorf("Expected %v, got %v", treeData, pt.Tree())
	}
}

func TestApplyUpdate(t *testing.T) {
	pt := pathtree.New()
	items := []*pathtree.PathItem{
		{[]string{"setting1"}, "69"},
		{[]string{"config", "setting2"}, `{"value": 42}`},
	}
	onError := func(err error) {
		t.Error("onError should not be called", err)
	}
	pt.ApplyUpdate(items, onError, pathtree.FormatJson)

	expectedTree := pathtree.TreeData{
		"setting1": float64(69),
		"config": map[string]interface{}{
			"setting2": map[string]interface{}{
				"value": float64(42),
			},
		},
	}

	if !reflect.DeepEqual(pt.Tree(), expectedTree) {
		t.Errorf("Expected %v, got %v", expectedTree, pt.Tree())
	}
}

func TestApplyRemove(t *testing.T) {

	treeData := pathtree.TreeData{
		"setting0": float64(69),
		"config": map[string]interface{}{
			"setting1": 42,
			"setting2": "goodbye",
		},
	}
	pt := pathtree.NewFrom(treeData)
	items := []*pathtree.PathItem{
		{[]string{"config", "setting1"}, ""},
	}
	onError := func(err error) {
		t.Error("onError should not be called", err)
	}
	pt.ApplyRemove(items, onError)

	expectedTree := pathtree.TreeData{
		"setting0": float64(69),
		"config": map[string]interface{}{
			"setting2": "goodbye",
		},
	}

	if !reflect.DeepEqual(pt.Tree(), expectedTree) {
		t.Errorf("Expected %v, got %v", expectedTree, pt.Tree())
	}
}

func TestSerialize(t *testing.T) {

	treeData := pathtree.TreeData{
		"config": map[string]interface{}{
			"setting1": "value1",
		},
	}
	pt := pathtree.NewFrom(treeData)

	postProcess := func(in any) any {
		return in
	}

	var expectedJson any

	serialized, err := pt.Serialize(pathtree.FormatJson, postProcess)
	if err != nil {
		t.Fatal("Serialize failed:", err)
	}

	if err := json.Unmarshal(serialized, &expectedJson); err != nil {
		t.Fatal("Failed to unmarshal JSON:", err)
	}

	if !reflect.DeepEqual(expectedJson, treeData) {
		t.Errorf("Expected %v, got %v", treeData, expectedJson)
	}

	var expectedYaml any

	// also test that a nil postProcess function works
	serializedYaml, err := pt.Serialize(pathtree.FormatYaml, nil)
	if err != nil {
		t.Fatal("Serialize to YAML failed:", err)
	}
	// Note: need to use yaml.v3 to unmarshal YAML data for compatibility with the
	// pathTree.Serialize() method, which uses yaml.v3.
	if err := yaml.Unmarshal(serializedYaml, &expectedYaml); err != nil {
		t.Fatal("Failed to unmarshal YAML:", err)
	}

	if !reflect.DeepEqual(expectedYaml, treeData) {
		t.Errorf("Expected %v, got %v", treeData, expectedYaml)
	}
}

func TestFlatten(t *testing.T) {

	treeData := pathtree.TreeData{
		"config": map[string]interface{}{
			"setting1": "value1",
			"nested": map[string]interface{}{
				"setting2": 42,
			},
		},
	}
	pt := pathtree.NewFrom(treeData)
	leaves := pt.Flatten()

	expectedLeaves := []pathtree.Leaf{
		{Path: []string{"config", "setting1"}, Value: "value1"},
		{Path: []string{"config", "nested", "setting2"}, Value: 42},
	}
	// Sort slices by joining keys into a single string
	sort.Slice(leaves, func(i, j int) bool {
		return strings.Join(leaves[i].Path, ".") < strings.Join(leaves[j].Path, ".")
	})

	sort.Slice(expectedLeaves, func(i, j int) bool {
		return strings.Join(expectedLeaves[i].Path, ".") < strings.Join(expectedLeaves[j].Path, ".")
	})

	if !reflect.DeepEqual(leaves, expectedLeaves) {
		t.Errorf("Expected %v, got %v", expectedLeaves, leaves)
	}
}

func TestFromItem(t *testing.T) {
	item := MockItem{
		key:       "",
		nestedKey: []string{"config", "setting2"},
		valueJson: `{"value": 42}`,
	}
	pathItem := pathtree.FromItem(item)

	expectedPathItem := &pathtree.PathItem{
		Path:  []string{"config", "setting2"},
		Value: `{"value": 42}`,
	}

	if !reflect.DeepEqual(pathItem, expectedPathItem) {
		t.Errorf("Expected %v, got %v", expectedPathItem, pathItem)
	}

	item = MockItem{key: "lol", valueJson: "420"}
	pathItem = pathtree.FromItem(item)

	expectedPathItem = &pathtree.PathItem{
		Path:  []string{"lol"},
		Value: "420",
	}

	if !reflect.DeepEqual(pathItem, expectedPathItem) {
		t.Errorf("Expected %v, got %v", expectedPathItem, pathItem)
	}
}

// TestFlattenEmptyTree checks behavior with an empty tree.
func TestFlattenEmptyTree(t *testing.T) {

	pt := pathtree.New()

	items, err := pt.FlattenAndSerialize(pathtree.FormatJson)
	if err != nil {
		t.Errorf("Error should not occur with empty tree: %v", err)
	}
	if len(items) != 0 {
		t.Errorf("Expected no items, got %d", len(items))
	}
}

// TestFlattenSpecialValuesFaluire checks behavior with NaN and Inf values.
// These values are not supported by JSON and should return an error.
func TestFlattenSpecialValuesFaluire(t *testing.T) {

	tree := pathtree.TreeData{
		"special": map[string]interface{}{
			"nan":  math.NaN(),
			"inf":  math.Inf(1),
			"ninf": math.Inf(-1),
		},
	}
	pt := pathtree.NewFrom(tree)

	_, err := pt.FlattenAndSerialize(pathtree.FormatJson)
	if err == nil {
		t.Error("Expected error for NaN or Inf values, got none")
	}
}

// TestFlattenSpecialValuesSuccess checks behavior with NaN and Inf values.
// These values are supported by JSONExt and should not return an error.
func TestFlattenSpecialValuesSuccess(t *testing.T) {

	tree := pathtree.TreeData{
		"special": map[string]interface{}{
			"nan":  math.NaN(),
			"inf":  math.Inf(1),
			"ninf": math.Inf(-1),
		},
	}
	pt := pathtree.NewFrom(tree)

	items, err := pt.FlattenAndSerialize(pathtree.FormatJsonExt)
	if err != nil {
		t.Error("Expected no error for NaN or Inf values, got:", err)
	}

	expected := []pathtree.PathItem{
		{Path: []string{"special", "nan"}, Value: "NaN"},
		{Path: []string{"special", "inf"}, Value: "Infinity"},
		{Path: []string{"special", "ninf"}, Value: "-Infinity"},
	}

	// Sort slices by joining keys into a single string for comparison
	// (since order is not guaranteed)
	sort.Slice(items, func(i, j int) bool {
		return strings.Join(items[i].Path, ".") < strings.Join(items[j].Path, ".")
	})

	sort.Slice(expected, func(i, j int) bool {
		return strings.Join(expected[i].Path, ".") < strings.Join(expected[j].Path, ".")
	})

	if !reflect.DeepEqual(items, expected) {
		t.Errorf("Expected %v, got %v", expected, items)
	}
}

// TestUnmarshalUnknownFormat checks behavior with an unknown format.
func TestUnmarshalUnknownFormat(t *testing.T) {

	tree := pathtree.TreeData{
		"config": map[string]interface{}{
			"setting1": "value1",
		},
	}
	pt := pathtree.NewFrom(tree)

	_, err := pt.Serialize(pathtree.Format(42), nil)
	if err == nil {
		t.Error("Expected error for unknown format, got none")
	}
}
