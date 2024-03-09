package watcher_test

import (
	"fmt"
	"os"
	"path/filepath"
	"syscall"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/watcher"
)

func writeEmptyFile(t *testing.T, path string) {
	require.NoError(t, os.MkdirAll(
		filepath.Dir(path),
		syscall.S_IRUSR|syscall.S_IWUSR|syscall.S_IXUSR))
	require.NoError(t, os.WriteFile(path, []byte(""), os.FileMode(0)))
}

func Test_WatchExistingFile_EmitsCreate(t *testing.T) {
	testFile := filepath.Join(t.TempDir(), "test.txt")
	writeEmptyFile(t, testFile)

	allEvents := make(chan watcher.Event, 1)
	w := watcher.New(watcher.Params{})
	w.Start()
	require.NoError(t,
		w.Add(testFile, func(e watcher.Event) error {
			allEvents <- e
			return nil
		}),
	)
	w.Close()

	lastEvent := <-allEvents
	assert.True(t, lastEvent.IsCreate())
}

func Test_WatchExistingDir_EmitsCreateForFiles(t *testing.T) {
	testDir := t.TempDir()
	for i := 1; i <= 5; i++ {
		writeEmptyFile(t, filepath.Join(testDir, fmt.Sprintf("file%v.txt", i)))
	}

	allEvents := make(chan watcher.Event, 5)
	w := watcher.New(watcher.Params{})
	w.Start()
	require.NoError(t,
		w.Add(testDir, func(e watcher.Event) error {
			if e.IsCreate() {
				allEvents <- e
			}
			return nil
		}))
	w.Close()

	// NOTE: Technically order isn't guaranteed.
	assert.EqualValues(t, "file1.txt", filepath.Base((<-allEvents).Path))
	assert.EqualValues(t, "file2.txt", filepath.Base((<-allEvents).Path))
	assert.EqualValues(t, "file3.txt", filepath.Base((<-allEvents).Path))
	assert.EqualValues(t, "file4.txt", filepath.Base((<-allEvents).Path))
	assert.EqualValues(t, "file5.txt", filepath.Base((<-allEvents).Path))
}

func Test_WatchRelativePath(t *testing.T) {
	filesDir := filepath.Join(t.TempDir(), "test_files")
	writeEmptyFile(t, filepath.Join(filesDir, "my_file.txt"))

	allEvents := make(chan watcher.Event, 1)
	w := watcher.New(watcher.Params{FilesDir: filesDir})
	w.Start()
	require.NoError(t,
		w.Add("my_file.txt", func(e watcher.Event) error {
			allEvents <- e
			return nil
		}))
	w.Close()

	assert.Equal(t,
		filepath.Join(filesDir, "my_file.txt"),
		(<-allEvents).Path)
}
