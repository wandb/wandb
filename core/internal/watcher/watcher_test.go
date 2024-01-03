package watcher_test

import (
	"os"
	"path/filepath"
	"sync"
	"testing"

	fw "github.com/radovskyb/watcher"
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

	cleanup := func() {
		os.Chdir(cwd)
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

func TestWatchFile(t *testing.T) {
	defer setupTest(t)()

	options := []watcher.WatcherOption{
		watcher.WithLogger(observability.NewNoOpLogger()),
	}
	w := watcher.New(options...)
	path := "test.txt"

	var wg sync.WaitGroup
	wg.Add(2)

	handlerCalled := 0
	handler := func(event watcher.Event) error {
		handlerCalled += 1
		require.Equal(t, filepath.Join("", path), event.Name())
		wg.Done()
		return nil
	}

	w.Start()

	os.WriteFile(path, []byte("testing\n"), 0644)
	err := w.Add(path, handler)
	require.NoError(t, err, "Registering path should be successful")

	info, _ := os.Stat(path)
	w.TriggerEvent(fw.Write, info)

	wg.Wait()
	require.Equal(t, 2, handlerCalled, "File event should have been handled twice and set handlerCalled to 2")

	w.Close()
}
