//go:build !windows

package paths_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/paths"
)

func TestAbsolute_RemovesTrailingSlash(t *testing.T) {
	path, err := paths.Absolute("/remove/slash/")

	require.NoError(t, err)
	assert.Equal(t, "/remove/slash", string(*path))
}

func TestAbsolute_GivenRelativePath_JoinsToCWD(t *testing.T) {
	cwd, err := paths.CWD()
	require.NoError(t, err)

	path, err := paths.Absolute(".")
	require.NoError(t, err)

	assert.Equal(t, string(*cwd), string(*path))
}

func TestRelative_CleansPath(t *testing.T) {
	path, err := paths.Relative("./../parent/../parent2/child/..")

	require.NoError(t, err)
	assert.Equal(t, "../parent2", string(*path))
}

func TestRelative_GivenAbsolutePath_Fails(t *testing.T) {
	path, err := paths.Relative("/absolute/path")

	assert.Nil(t, path)
	assert.ErrorContains(t, err, `path is not relative: "/absolute/path"`)
}

func TestJoin(t *testing.T) {
	path1, err := paths.Absolute("/absolute/path")
	require.NoError(t, err)
	path2, err := paths.Relative("../relative/path")
	require.NoError(t, err)

	result := path1.Join(*path2)

	assert.Equal(t, "/absolute/relative/path", string(result))
}

func TestIsLocal_LocalPath_True(t *testing.T) {
	path, err := paths.Relative("local/../path")
	require.NoError(t, err)

	assert.True(t, path.IsLocal())
}

func TestIsLocal_NonLocalPath_False(t *testing.T) {
	path, err := paths.Relative("../non/local/path")
	require.NoError(t, err)

	assert.False(t, path.IsLocal())
}
