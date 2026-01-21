package runconsolelogs_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/runconsolelogs"
	"github.com/wandb/wandb/core/internal/sparselist"
)

func TestCreateLineFile_TruncatesExistingFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "out.txt")
	require.NoError(t, os.WriteFile(path, []byte("content\n"), 0o644))

	_, err := runconsolelogs.CreateLineFile(path, 0o644)

	assert.NoError(t, err)
	content, err := os.ReadFile(path)
	require.NoError(t, err)
	assert.Empty(t, content)
}

func TestUpdateLines(t *testing.T) {
	path := filepath.Join(t.TempDir(), "out.txt")
	file, err := runconsolelogs.CreateLineFile(path, 0o644)
	require.NoError(t, err)

	// TEST: Append new lines.
	lines := &sparselist.SparseList[string]{}
	lines.Put(0, "one")
	lines.Put(1, "two")
	lines.Put(3, "four")
	assert.NoError(t, file.UpdateLines(lines))

	content, err := os.ReadFile(path)
	require.NoError(t, err)
	assert.Equal(t,
		"one\ntwo\n\nfour\n",
		string(content))

	// TEST: Modify old lines, use non-ASCII characters.
	lines = &sparselist.SparseList[string]{}
	lines.Put(1, "two 💥") // 💥 takes 4 UTF-8 codepoints
	lines.Put(2, "three, added")
	lines.Put(6, "seven, new")
	assert.NoError(t, file.UpdateLines(lines))

	content, err = os.ReadFile(path)
	require.NoError(t, err)
	assert.Equal(t,
		"one\ntwo 💥\nthree, added\nfour\n\n\nseven, new\n",
		string(content))
}
