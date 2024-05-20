package watcher_test

import (
	"os"
	"path/filepath"
	"syscall"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/waitingtest"
	"github.com/wandb/wandb/core/internal/watcher"
)

func waitWithDeadline[S any](t *testing.T, c <-chan S, msg string) S {
	t.Helper()
	select {
	case x := <-c:
		return x
	case <-time.After(time.Second):
		t.Fatal("took too long: " + msg)
		panic("unreachable")
	}
}

// testContext is a set of variables and functions available in all tests.
type testContext struct {
	Watcher          watcher.Watcher
	PollingStopwatch *waitingtest.FakeStopwatch
	WriteFile        func(slashPath, content string)
	DeleteFile       func(slashPath string)

	// AbsPath converts a slash-separated relative path to a correctly formatted
	// path to a temporary file.
	AbsPath func(slashPath string) string

	// RelPath is like AbsPath but returns a path relative to the current
	// working directory.
	RelPath func(slashPath string) string

	// LogID0 returns a function to pass to Watch() that records
	// calls to itself.
	LogID0 func(id string) func()

	// LogID1 returns a function to pass to WatchTree() that records
	// calls to itself.
	LogID1 func(id string) func(path string)

	// ExpectLoggedID fails the test if a LogID0 or LogID1 call has not
	// occurred and does not occur within a timeout.
	//
	// The "slashPath" argument is the path given to the WatchTree callback
	// or the empty string if this is a Watch callback.
	ExpectLoggedID func(id, slashPath string)
}

type capturedFileCallback struct {
	ID   string
	Path string
}

// setupTest creates a testContext for writing Watcher tests.
func setupTest(t *testing.T) testContext {
	ctx := testContext{}

	ctx.PollingStopwatch = waitingtest.NewFakeStopwatch()
	ctx.Watcher = watcher.New(watcher.Params{
		PollingStopwatch: ctx.PollingStopwatch,
	})
	t.Cleanup(func() {
		done := make(chan struct{})

		go func() {
			ctx.Watcher.Finish()
			done <- struct{}{}
		}()

		waitWithDeadline(t, done, "expected Finish to complete")
	})

	tmpdir := t.TempDir()
	ctx.AbsPath = func(slashPath string) string {
		t.Helper()
		absPath, err := filepath.Abs(
			filepath.Join(tmpdir, filepath.FromSlash(slashPath)),
		)
		require.NoError(t, err)
		return absPath
	}
	ctx.RelPath = func(slashPath string) string {
		t.Helper()

		cwd, err := os.Getwd()
		require.NoError(t, err)

		relPath, err := filepath.Rel(cwd, ctx.AbsPath(slashPath))
		require.NoError(t, err)

		return relPath
	}

	ctx.WriteFile = func(slashPath, content string) {
		t.Helper()
		path := ctx.AbsPath(slashPath)
		require.NoError(t,
			os.MkdirAll(filepath.Dir(path), os.ModePerm))
		require.NoError(t,
			os.WriteFile(
				path,
				[]byte(content),
				syscall.S_IRUSR|syscall.S_IWUSR,
			))
	}

	ctx.DeleteFile = func(slashPath string) {
		t.Helper()
		require.NoError(t, os.Remove(ctx.AbsPath(slashPath)))
	}

	idChan := make(chan capturedFileCallback)
	ctx.LogID0 = func(id string) func() {
		return func() { idChan <- capturedFileCallback{id, ""} }
	}
	ctx.LogID1 = func(id string) func(string) {
		return func(path string) { idChan <- capturedFileCallback{id, path} }
	}
	ctx.ExpectLoggedID = func(id, slashPath string) {
		t.Helper()

		captured := waitWithDeadline(t, idChan,
			"expected file callback to be called")

		var expectedPath string
		if slashPath == "" {
			expectedPath = slashPath
		} else {
			expectedPath = ctx.AbsPath(slashPath)
		}

		if captured.ID != id || captured.Path != expectedPath {
			t.Errorf(
				"expected callback '%v' to be called with path '%v'"+
					" but got callback '%v' with path '%v'",
				id,
				expectedPath,
				captured.ID,
				captured.Path,
			)
		}
	}

	return ctx
}

func TestWatcher(t *testing.T) {
	t.Run("runs callback for new file", func(t *testing.T) {
		ctx := setupTest(t)

		require.NoError(t,
			ctx.Watcher.Watch(
				ctx.RelPath("file.txt"),
				ctx.LogID0("watch"),
			))
		ctx.WriteFile("file.txt", "")
		ctx.PollingStopwatch.SetDone()

		ctx.ExpectLoggedID("watch", "")
	})

	t.Run("runs callback for modified file", func(t *testing.T) {
		ctx := setupTest(t)
		ctx.WriteFile("file.txt", "initial")

		require.NoError(t,
			ctx.Watcher.Watch(
				ctx.RelPath("file.txt"),
				ctx.LogID0("watch"),
			))
		ctx.WriteFile("file.txt", "modified")
		ctx.PollingStopwatch.SetDone()

		ctx.ExpectLoggedID("watch", "")
	})

	t.Run("runs callback for deleted file", func(t *testing.T) {
		ctx := setupTest(t)
		ctx.WriteFile("file.txt", "content 1")

		require.NoError(t,
			ctx.Watcher.Watch(
				ctx.RelPath("file.txt"),
				ctx.LogID0("watch"),
			))
		ctx.DeleteFile("file.txt")
		ctx.PollingStopwatch.SetDone()

		ctx.ExpectLoggedID("watch", "")
	})

	t.Run("runs callback for nested file in tree", func(t *testing.T) {
		ctx := setupTest(t)
		ctx.WriteFile("dir/unchanged.txt", "")

		require.NoError(t,
			ctx.Watcher.WatchTree(
				ctx.RelPath("dir"),
				ctx.LogID1("watch"),
			))
		ctx.WriteFile("dir/subdir/new.txt", "")
		ctx.PollingStopwatch.SetDone()

		ctx.ExpectLoggedID("watch", "dir/subdir/new.txt")
	})
}
