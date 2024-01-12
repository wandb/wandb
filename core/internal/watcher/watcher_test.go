package watcher_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/watcher"
	"github.com/wandb/wandb/core/pkg/observability"
)

func setupTest(t *testing.T) func() {
	tmpDir, err := os.MkdirTemp("", "watcher_tests")
	require.NoError(t, err, "cannot create temp directory")
	cwd, err := os.Getwd()
	require.NoError(t, err, "cannot get current working directory")
	require.NoError(t, os.Chdir(tmpDir), "cannot switch to temp directory")

	err = os.Mkdir(filepath.Join(tmpDir, "test"), 0755)
	require.NoError(t, err, "Creating directory should be successful")

	err = os.WriteFile(filepath.Join(tmpDir, "test.txt"), []byte("testing"), 0644)
	require.NoError(t, err, "Writing file should be successful")

	cleanup := func() {
		err := os.Chdir(cwd)
		require.NoError(t, err, "cannot switch back to original directory")
		os.RemoveAll(tmpDir)
	}
	return cleanup
}

func TestNew(t *testing.T) {
	defer setupTest(t)()

	logger := observability.NewNoOpLogger()

	options := []watcher.WatcherOption{
		watcher.WithLogger(logger),
	}
	w := watcher.New(options...)

	require.NotNil(t, w, "Watcher should not be nil")
}

// func TestWatchFile(t *testing.T) {
// 	defer setupTest(t)()

// 	options := []watcher.WatcherOption{
// 		watcher.WithLogger(observability.NewNoOpLogger()),
// 	}
// 	w := watcher.New(options...)
// 	path := "test.txt"

// 	var wg sync.WaitGroup
// 	wg.Add(1)

// 	handler := func(event watcher.Event) error {
// 		if !event.IsDir() {
// 			require.Equal(t, filepath.Join("", path), event.Name())
// 			wg.Done()
// 		}

// 		return nil
// 	}

// 	w.Start()

// 	err := w.Add(path, handler)
// 	require.NoError(t, err, "Registering path should be successful")

// 	// write a file in the directory
// 	err = os.WriteFile(path, []byte("testing"), 0644)
// 	require.NoError(t, err, "Writing file should be successful")

// 	wg.Wait()
// 	w.Close()
// }

// func TestWatchDir(t *testing.T) {
// 	defer setupTest(t)()

// 	options := []watcher.WatcherOption{
// 		watcher.WithLogger(observability.NewNoOpLogger()),
// 	}
// 	w := watcher.New(options...)
// 	path := "test"

// 	var wg sync.WaitGroup
// 	wg.Add(1)

// 	handler := func(event watcher.Event) error {
// 		if !event.IsDir() {
// 			require.Equal(t, filepath.Join("", path), filepath.Base(filepath.Dir(event.Path)))
// 			wg.Done()
// 		}

// 		return nil
// 	}

// 	w.Start()

// 	err := w.Add(path, handler)
// 	require.NoError(t, err, "Registering path should be successful")

// 	// write a file in the directory
// 	err = os.WriteFile(filepath.Join(path, "test.txt"), []byte("testing"), 0644)
// 	require.NoError(t, err, "Writing file should be successful")

// 	wg.Wait()
// 	w.Close()
// }
