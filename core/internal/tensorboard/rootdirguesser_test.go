package tensorboard_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/tensorboard"
)

func TestInfer_FewerThan2Directories_Fails(t *testing.T) {
	guesser := tensorboard.NewRootDirGuesser(observability.NewNoOpLogger())
	path, err := tensorboard.ParseTBPath("/log/dir")
	require.NoError(t, err)

	guesser.AddLogDirectory(path)
	root := guesser.InferRootOrTimeout(path, 0)

	assert.Nil(t, root)
}

func TestInfer(t *testing.T) {
	guesser := tensorboard.NewRootDirGuesser(observability.NewNoOpLogger())

	localPath1, err := tensorboard.ParseTBPath("/tblogs/train")
	require.NoError(t, err)
	localPath2, err := tensorboard.ParseTBPath("/tblogs/validate")
	require.NoError(t, err)

	cloudPath1, err := tensorboard.ParseTBPath("gs://bucket/tblogs/train")
	require.NoError(t, err)
	cloudPath2, err := tensorboard.ParseTBPath("gs://bucket/tblogs/validate")
	require.NoError(t, err)

	guesser.AddLogDirectory(localPath1)
	guesser.AddLogDirectory(localPath2)
	guesser.AddLogDirectory(cloudPath1)
	guesser.AddLogDirectory(cloudPath2)

	t.Run("local paths", func(t *testing.T) {
		root := guesser.InferRootOrTimeout(localPath2, 0)
		assert.Equal(t, "/tblogs", root.String())
	})

	t.Run("cloud paths", func(t *testing.T) {
		root := guesser.InferRootOrTimeout(cloudPath2, 0)
		assert.Equal(t, "bucket/tblogs", root.String())
	})
}

func TestTrim_DropsLeadingSlash(t *testing.T) {
	rootDir := tensorboard.NewRootDir("prefix")
	path, err := tensorboard.ParseTBPath("s3://prefix/file")
	require.NoError(t, err)

	result, err := rootDir.TrimFrom(path)

	require.NoError(t, err)
	assert.Equal(t, "file", result) // not "/file"
}

func TestTrim_PrefixNotPresent_Fails(t *testing.T) {
	rootDir := tensorboard.NewRootDir("prefix")
	path, err := tensorboard.ParseTBPath("s3://not-prefix/file")
	require.NoError(t, err)

	result, err := rootDir.TrimFrom(path)

	assert.Empty(t, result)
	assert.ErrorContains(t, err, `"not-prefix/file" does not start with "prefix"`)
}
