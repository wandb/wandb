package pathtree_test

import (
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/pathtree"
)

func TestForEachTopLevel(t *testing.T) {
	tree := pathtree.New[any]()
	tree.Set(pathtree.PathOf("z"), nil)
	tree.Set(pathtree.PathOf("a", "b", "c"), int64(1))
	tree.Set(pathtree.PathOf("a.b"), "literal")
	var keys []string
	values := make(map[string]any)
	tree.ForEachTopLevel(func(key string, value any) {
		keys = append(keys, key)
		values[key] = value
	})
	assert.Equal(t, []string{"a", "a.b", "z"}, keys)
	assert.Equal(t, map[string]any{
		"a":   map[string]any{"b": map[string]any{"c": int64(1)}},
		"a.b": "literal", "z": nil,
	}, values)
	values["a"].(map[string]any)["b"].(map[string]any)["c"] = int64(2)
	value, exists := tree.GetLeaf(pathtree.PathOf("a", "b", "c"))
	assert.True(t, exists)
	assert.Equal(t, int64(1), value)
}

func TestForEachTopLevelEmpty(t *testing.T) {
	pathtree.New[int]().ForEachTopLevel(func(string, any) {
		t.Fatal("empty tree yielded a node")
	})
}

func TestSet_NewNode(t *testing.T) {
	tree := pathtree.New[int]()

	tree.Set(pathtree.PathOf("a", "b"), 1)
	tree.Set(pathtree.PathOf("a", "c", "d"), 2)

	ab, abExists := tree.GetLeaf(pathtree.PathOf("a", "b"))
	acd, acdExists := tree.GetLeaf(pathtree.PathOf("a", "c", "d"))
	assert.True(t, abExists)
	assert.Equal(t, 1, ab)
	assert.True(t, acdExists)
	assert.Equal(t, 2, acd)
}

func TestSet_OverwriteLeaf(t *testing.T) {
	tree := pathtree.New[int]()

	tree.Set(pathtree.PathOf("a"), 1)
	tree.Set(pathtree.PathOf("a", "b"), 2)

	a, aExists := tree.GetLeaf(pathtree.PathOf("a"))
	ab, abExists := tree.GetLeaf(pathtree.PathOf("a", "b"))
	assert.False(t, aExists)
	assert.Zero(t, a)
	assert.True(t, abExists)
	assert.Equal(t, 2, ab)
}

func TestRemove_Leaf(t *testing.T) {
	tree := pathtree.New[int]()

	tree.Set(pathtree.PathOf("a", "b"), 1)
	tree.Set(pathtree.PathOf("a", "c"), 2)
	tree.Remove(pathtree.PathOf("a", "b"))

	ab, abExists := tree.GetLeaf(pathtree.PathOf("a", "b"))
	ac, acExists := tree.GetLeaf(pathtree.PathOf("a", "c"))
	assert.False(t, abExists)
	assert.Zero(t, ab)
	assert.True(t, acExists)
	assert.Equal(t, 2, ac)
}

func TestRemove_Node(t *testing.T) {
	tree := pathtree.New[int]()

	tree.Set(pathtree.PathOf("a", "b", "c"), 1)
	tree.Set(pathtree.PathOf("a", "d"), 2)
	tree.Remove(pathtree.PathOf("a", "b"))

	abc, abcExists := tree.GetLeaf(pathtree.PathOf("a", "b", "c"))
	ad, adExists := tree.GetLeaf(pathtree.PathOf("a", "d"))
	assert.False(t, abcExists)
	assert.Zero(t, abc)
	assert.True(t, adExists)
	assert.Equal(t, 2, ad)
}

func TestRemove_DeletesParentMaps(t *testing.T) {
	tree := pathtree.New[int]()

	tree.Set(pathtree.PathOf("a", "b", "c"), 1)
	tree.Remove(pathtree.PathOf("a", "b", "c"))

	// IsEmpty() just checks the length of the root map. If we don't
	// remove parent maps, this will fail.
	assert.True(t, tree.IsEmpty())
}

func TestGetLeaf_UnderLeaf(t *testing.T) {
	tree := pathtree.New[int]()

	tree.Set(pathtree.PathOf("a"), 1)

	x, exists := tree.GetLeaf(pathtree.PathOf("a", "b"))
	assert.False(t, exists)
	assert.Zero(t, x)
}

func TestGetLeaf_PathIsNotLeaf(t *testing.T) {
	tree := pathtree.New[int]()

	tree.Set(pathtree.PathOf("a", "b"), 1)

	x, exists := tree.GetLeaf(pathtree.PathOf("a"))
	assert.False(t, exists)
	assert.Zero(t, x)
}

func TestGetOrMakeLeaf_PathIsNotLeaf(t *testing.T) {
	tree := pathtree.New[int]()

	tree.Set(pathtree.PathOf("a", "b"), 1)

	x := tree.GetOrMakeLeaf(pathtree.PathOf("a"), func() int { return 2 })
	assert.Equal(t, 2, x)
}

func TestFlatten(t *testing.T) {
	tree := pathtree.New[int]()

	tree.Set(pathtree.PathOf("a", "b"), 1)
	tree.Set(pathtree.PathOf("a", "c"), 2)
	tree.Set(pathtree.PathOf("a", "d", "e"), 3)
	leaves := tree.Flatten()

	assert.Len(t, leaves, 3)
	assert.Contains(t, leaves,
		pathtree.PathItem{
			Path:  pathtree.PathOf("a", "b"),
			Value: 1,
		})
	assert.Contains(t, leaves,
		pathtree.PathItem{
			Path:  pathtree.PathOf("a", "c"),
			Value: 2,
		})
	assert.Contains(t, leaves,
		pathtree.PathItem{
			Path:  pathtree.PathOf("a", "d", "e"),
			Value: 3,
		})
}
