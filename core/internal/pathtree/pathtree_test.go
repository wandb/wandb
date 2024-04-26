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
