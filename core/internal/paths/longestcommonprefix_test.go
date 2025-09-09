package paths_test

import (
	"slices"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/paths"
)

func absPath(t *testing.T, path string) paths.AbsolutePath {
	p, err := paths.Absolute(path)
	require.NoError(t, err)
	return *p
}

func TestLongestCommonPrefix(t *testing.T) {
	prefix, err := paths.LongestCommonPrefix(
		[]paths.AbsolutePath{
			absPath(t, "/one/two/three"),
			absPath(t, "/one/two"),
			absPath(t, "/one/ten"),
		},
	)

	assert.NoError(t, err)
	assert.Equal(t,
		absPath(t, "/one"),
		*prefix,
	)
}

func TestLongestCommonPrefix_TooFewDirectories(t *testing.T) {
	prefix, err := paths.LongestCommonPrefix(
		[]paths.AbsolutePath{absPath(t, "/one/two")},
	)

	assert.ErrorContains(t, err, "too few paths")
	assert.Nil(t, prefix)
}

func TestLongestCommonPrefixStr_OfSingleString_IsInput(t *testing.T) {
	prefix := paths.LongestCommonPrefixStr(
		slices.Values([]string{"some/strange//path/"}),
		"/",
	)

	assert.Equal(t, "some/strange//path/", prefix)
}

func TestLongestCommonPrefixStr_OfNothing_Empty(t *testing.T) {
	prefix := paths.LongestCommonPrefixStr(
		slices.Values([]string{}),
		"/",
	)

	assert.Equal(t, "", prefix)
}

func TestLongestCommonPrefixStr_ComparesComponents(t *testing.T) {
	prefix := paths.LongestCommonPrefixStr(
		slices.Values([]string{
			"parent_child",
			"parent_children",
		}),
		"_",
	)

	// NOTE: Not "parent_child".
	assert.Equal(t, "parent", prefix)
}
