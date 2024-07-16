package pathtree_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/pathtree"
)

func TestSet_NewNode(t *testing.T) {
	tree := pathtree.New()

	tree.Set(pathtree.TreePath{"a", "b"}, 1)
	tree.Set(pathtree.TreePath{"a", "c", "d"}, 2)

	ab, abExists := tree.GetLeaf(pathtree.TreePath{"a", "b"})
	acd, acdExists := tree.GetLeaf(pathtree.TreePath{"a", "c", "d"})
	assert.True(t, abExists)
	assert.Equal(t, 1, ab)
	assert.True(t, acdExists)
	assert.Equal(t, 2, acd)
}

func TestSet_OverwriteLeaf(t *testing.T) {
	tree := pathtree.New()

	tree.Set(pathtree.TreePath{"a"}, 1)
	tree.Set(pathtree.TreePath{"a", "b"}, 2)

	a, aExists := tree.GetLeaf(pathtree.TreePath{"a"})
	ab, abExists := tree.GetLeaf(pathtree.TreePath{"a", "b"})
	assert.False(t, aExists)
	assert.Nil(t, a)
	assert.True(t, abExists)
	assert.Equal(t, 2, ab)
}

func TestRemove_Leaf(t *testing.T) {
	tree := pathtree.New()

	tree.Set(pathtree.TreePath{"a", "b"}, 1)
	tree.Set(pathtree.TreePath{"a", "c"}, 2)
	tree.Remove(pathtree.TreePath{"a", "b"})

	ab, abExists := tree.GetLeaf(pathtree.TreePath{"a", "b"})
	ac, acExists := tree.GetLeaf(pathtree.TreePath{"a", "c"})
	assert.False(t, abExists)
	assert.Nil(t, ab)
	assert.True(t, acExists)
	assert.Equal(t, 2, ac)
}

func TestRemove_Node(t *testing.T) {
	tree := pathtree.New()

	tree.Set(pathtree.TreePath{"a", "b", "c"}, 1)
	tree.Set(pathtree.TreePath{"a", "d"}, 2)
	tree.Remove(pathtree.TreePath{"a", "b"})

	abc, abcExists := tree.GetLeaf(pathtree.TreePath{"a", "b", "c"})
	ad, adExists := tree.GetLeaf(pathtree.TreePath{"a", "d"})
	assert.False(t, abcExists)
	assert.Nil(t, abc)
	assert.True(t, adExists)
	assert.Equal(t, 2, ad)
}

func TestRemove_DeletesParentMaps(t *testing.T) {
	tree := pathtree.New()

	tree.Set(pathtree.TreePath{"a", "b", "c"}, 1)
	tree.Remove(pathtree.TreePath{"a", "b", "c"})

	// IsEmpty() just checks the length of the root map. If we don't
	// remove parent maps, this will fail.
	assert.True(t, tree.IsEmpty())
}

func TestGetLeaf_UnderLeaf(t *testing.T) {
	tree := pathtree.New()

	tree.Set(pathtree.TreePath{"a"}, 1)

	x, exists := tree.GetLeaf(pathtree.TreePath{"a", "b"})
	assert.False(t, exists)
	assert.Nil(t, x)
}

func TestFlatten(t *testing.T) {
	tree := pathtree.New()

	tree.Set(pathtree.TreePath{"a", "b"}, 1)
	tree.Set(pathtree.TreePath{"a", "c"}, 2)
	tree.Set(pathtree.TreePath{"a", "d", "e"}, 3)
	leaves := tree.Flatten()

	assert.Len(t, leaves, 3)
	assert.Contains(t, leaves,
		pathtree.PathItem{
			Path:  pathtree.TreePath{"a", "b"},
			Value: 1,
		})
	assert.Contains(t, leaves,
		pathtree.PathItem{
			Path:  pathtree.TreePath{"a", "c"},
			Value: 2,
		})
	assert.Contains(t, leaves,
		pathtree.PathItem{
			Path:  pathtree.TreePath{"a", "d", "e"},
			Value: 3,
		})
}
