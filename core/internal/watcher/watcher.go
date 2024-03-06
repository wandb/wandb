package watcher

import (
	"fmt"
	"os"
	"path/filepath"
	"time"

	fw "github.com/radovskyb/watcher"
	"github.com/wandb/wandb/core/pkg/observability"
)

const pollingInterval = time.Millisecond * 100

type Watcher struct {
	watcher  *fw.Watcher
	logger   *observability.CoreLogger
	registry *registry
	filesDir string
}

type Params struct {
	Logger *observability.CoreLogger

	// The directory where files are stored.
	//
	// Used as the base for relative file paths.
	FilesDir string
}

func New(params Params) *Watcher {
	return &Watcher{
		watcher:  fw.New(),
		logger:   params.Logger,
		registry: &registry{},
		filesDir: params.FilesDir,
	}
}

// Begin polling files and emitting events.
func (w *Watcher) Start() {
	// Begin polling.
	go func() {
		if err := w.watcher.Start(pollingInterval); err != nil {
			w.logger.CaptureError("watcher: error starting", err)
		}
	}()

	// Begin processing events.
	go func() {
		w.logger.Debug("watcher: starting")
		if err := w.watchLoop(); err != nil {
			w.logger.CaptureError("watcher: error watching", err)
		}
	}()
}

// Stops polling and cleans up.
func (w *Watcher) Close() {
	w.watcher.Close()
	w.logger.Debug("watcher: closed")
}

// Begin watching a path and invoking the given callback on each event.
//
// The given path must exist.
//
// Relative paths are relative to the configured FilesDir, which may itself
// be relative to the working directory.
//
// A Create event is emitted immediately for regular files. When given a
// directory, the callback is used for any direct children of the directory
// that don't have a handler otherwise; a Create event is emitted for all
// existing children of the directory.
func (w *Watcher) Add(path string, fn func(Event) error) error {
	if !filepath.IsAbs(path) {
		path = filepath.Join(w.filesDir, path)
	}

	info, err := os.Stat(path)
	if err != nil {
		return fmt.Errorf("watcher: failed to add path: %v", err)
	}

	if info.IsDir() {
		return w.addFile(path, info, fn)
	} else {
		return w.addDirectory(path, fn)
	}
}

// Runs the registered handler for a file event.
func (w *Watcher) handleEvent(event Event) error {
	w.logger.Debug("watcher: got event", "event", event)
	if fn, ok := w.registry.get(event.Path); ok {
		return fn(event)
	}
	if fn, ok := w.registry.get(filepath.Dir(event.Path)); ok {
		return fn(event)
	}

	return nil
}

// Loop and handle file events from the watcher.
//
// Returns when the watcher is closed or an error occurs.
func (w *Watcher) watchLoop() error {
	w.logger.Debug("starting watcher")
	for {
		select {
		case event := <-w.watcher.Event:
			w.logger.Debug("got event", "event", event)
			if err := w.handleEvent(Event{Event: event}); err != nil {
				w.logger.CaptureError("error handling event", err, "event", event)
			}
		case err := <-w.watcher.Error:
			w.logger.CaptureError("error from watcher", err)
			return err
		case <-w.watcher.Closed:
			w.logger.Debug("watcher closed")
			return nil
		}
	}
}

func (w *Watcher) addFile(path string, info os.FileInfo, fn func(Event) error) error {
	if err := w.watcher.Add(path); err != nil {
		return fmt.Errorf("watcher: failed to watch file: %v", err)
	}

	w.registry.register(path, fn)

	w.watcher.Wait()
	w.watcher.TriggerEvent(fw.Create, &EventFileInfo{
		FileInfo: info,
		name:     path,
	})

	return nil
}

func (w *Watcher) addDirectory(path string, fn func(Event) error) error {
	files, err := os.ReadDir(path)
	if err != nil {
		return fmt.Errorf("watcher: failed to read directory: %v", err)
	}

	if err := w.watcher.Add(path); err != nil {
		return fmt.Errorf("watcher: failed to watch directory: %v", err)
	}

	w.registry.register(path, fn)

	w.watcher.Wait()
	for _, file := range files {
		info, err := file.Info()
		if err != nil {
			w.logger.CaptureError(
				"watcher: failed to emit Create event for file in directory",
				err,
			)

			// Skip errors -- we already started watching!
			continue
		}

		w.watcher.TriggerEvent(fw.Create, &EventFileInfo{
			FileInfo: info,
			name:     filepath.Join(path, file.Name()),
		})
	}

	return nil
}
