package pathtree_test

import (
	"reflect"
	"sort"
	"strings"
	"testing"

	"github.com/wandb/wandb/core/internal/pathtree"
)

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
	pt.ApplyRemove(items)

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


	expectedLeaves := []pathtree.PathItem{
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

// TestFlattenEmptyTree checks behavior with an empty tree.
func TestFlattenEmptyTree(t *testing.T) {

	pt := pathtree.New()

	items := pt.Flatten()

	if len(items) != 0 {
		t.Errorf("Expected no items, got %d", len(items))
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
