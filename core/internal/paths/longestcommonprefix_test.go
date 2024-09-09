package paths_test

import (
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
			absPath(t, "/one/two"),
			absPath(t, "/one/two/three"),
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
