package tensorboard_test

import (
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	. "github.com/wandb/wandb/core/internal/tensorboard"
)

func TestPrefixFileNamer(t *testing.T) {
	t.Run("prefixes name of local file", func(t *testing.T) {
		fileNamer := PrefixFileNamer(filepath.Join("some", "prefix"))
		localPath, err := ParseTBPath("/home/someuser/validation/tfevents")
		require.NoError(t, err)

		name, err := fileNamer(localPath)

		require.NoError(t, err)
		assert.Equal(t, filepath.Join("some", "prefix", "tfevents"), name)
	})

	t.Run("rejects cloud path", func(t *testing.T) {
		fileNamer := PrefixFileNamer(filepath.Join("some", "prefix"))
		cloudPath, err := ParseTBPath("s3://my-bucket/train/tfevents")
		require.NoError(t, err)

		_, err = fileNamer(cloudPath)

		assert.ErrorContains(t, err, "not a local file")
	})
}
