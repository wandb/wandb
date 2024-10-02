package watcher_test

import (
	"os"
	"path/filepath"
	"syscall"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/watcher"
)

func mkdir(t *testing.T, path string) {
	require.NoError(t,
		os.MkdirAll(
			path,
			syscall.S_IRUSR|syscall.S_IWUSR|syscall.S_IXUSR,
		))
}

func writeFileAndGetModTime(t *testing.T, path string, content string) time.Time {
	mkdir(t, filepath.Dir(path))

	require.NoError(t,
		os.WriteFile(path, []byte(content), syscall.S_IRUSR|syscall.S_IWUSR))

	info, err := os.Stat(path)
	require.NoError(t, err)

	return info.ModTime()
}

func writeFile(t *testing.T, path string, content string) {
	_ = writeFileAndGetModTime(t, path, content)
}

func waitWithDeadline[S any](t *testing.T, c <-chan S, msg string) S {
	select {
	case x := <-c:
		return x
	case <-time.After(5 * time.Second):
		t.Fatal("took too long: " + msg)
		panic("unreachable")
	}
}

func TestWatcher(t *testing.T) {
	// The watcher implementation we rely on uses `time.Sleep()`, making for
	// flaky and slow tests. The tests in this function are carefully designed
	// to be fast and unlikely to flake.
	//
	// 1. We use a short polling period
	// 2. The success path for each test is designed to finish quickly
	// 3. Tests fail if they exceed a large deadline
	//
	// When the code is correct, these tests will complete very quickly,
	// *especially* if running locally. In CI, `time.Sleep()` could take longer
	// on a busy processor, but it's unlikely to reach (3) and flake.
	//
	// The downside of (3) is that if the code is *not* correct, then the
	// tests take a long time to fail. This can be an annoying dev
	// cycle for someone working on this package. So you should try to write
	// bug-free code :)

	newTestWatcher := func() watcher.Watcher {
		return watcher.New(watcher.Params{
			PollingPeriod: 10 * time.Millisecond,
		})
	}
	finishWithDeadline := func(t *testing.T, w watcher.Watcher) {
		finished := make(chan struct{})

		go func() {
			w.Finish()
			finished <- struct{}{}
		}()

		waitWithDeadline(t, finished, "expected Finish() to complete")
	}

	t.Run("runs callback on file write", func(t *testing.T) {
		t.Parallel()

		onChangeChan := make(chan struct{})
		file := filepath.Join(t.TempDir(), "file.txt")
		t1 := writeFileAndGetModTime(t, file, "")

		watcher := newTestWatcher()
		defer finishWithDeadline(t, watcher)
		require.NoError(t,
			watcher.Watch(file, func() { onChangeChan <- struct{}{} }))
		time.Sleep(100 * time.Millisecond) // see below
		t2 := writeFileAndGetModTime(t, file, "xyz")

		if t1 == t2 {
			// We sleep before updating the file to try to increase the
			// likelihood of the second write updating the file's ModTime.
			//
			// The ModTime (mtime) is sometimes not very precise, causing
			// the file to look unchanged to the poll-based watcher that
			// we use.
			//
			// Great blog post about it: https://apenwarr.ca/log/20181113
			t.Skip("test ran too fast and mtime didn't change")
		}

		waitWithDeadline(t, onChangeChan,
			"expected file callback to be called")
	})

	t.Run("runs callback on new file in directory", func(t *testing.T) {
		t.Parallel()

		onChangeChan := make(chan string)
		dir := filepath.Join(t.TempDir(), "dir")
		file := filepath.Join(dir, "file.txt")
		mkdir(t, dir)

		watcher := newTestWatcher()
		defer finishWithDeadline(t, watcher)
		require.NoError(t,
			watcher.WatchDir(dir, func(s string) { onChangeChan <- s }))
		writeFile(t, file, "")

		result := waitWithDeadline(t, onChangeChan,
			"expected file callback to be called")
		assert.Equal(t, result, file)
	})

	t.Run("fails if file does not exist", func(t *testing.T) {
		t.Parallel()

		file := filepath.Join(t.TempDir(), "file.txt")

		watcher := newTestWatcher()
		defer finishWithDeadline(t, watcher)
		err := watcher.Watch(file, func() {})

		require.Error(t, err)
	})

	t.Run("fails if Watch is called after Finish", func(t *testing.T) {
		t.Parallel()

		file := filepath.Join(t.TempDir(), "file.txt")
		writeFile(t, file, "")

		watcher := newTestWatcher()
		finishWithDeadline(t, watcher)
		err := watcher.Watch(file, func() {})

		require.ErrorContains(t, err, "tried to call Watch() after Finish()")
	})
}
