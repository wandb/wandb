package watcher

import (
	"os"
	"path/filepath"
	"sync"
	"time"

	fw "github.com/radovskyb/watcher"

	"github.com/wandb/wandb/core/internal/observability"
)

const pollingInterval = time.Millisecond * 100

type Watcher struct {
	watcher  *fw.Watcher
	wg       *sync.WaitGroup
	logger   *observability.CoreLogger
	registry *registry
}

type WatcherOption func(*Watcher)

func WithLogger(logger *observability.CoreLogger) WatcherOption {
	return func(w *Watcher) {
		w.logger = logger
	}
}

func New(opts ...WatcherOption) *Watcher {
	w := &Watcher{
		watcher:  fw.New(),
		wg:       &sync.WaitGroup{},
		registry: &registry{},
	}
	for _, opt := range opts {
		opt(w)
	}
	return w
}

// handleEvent handles an event from the watcher and calls the appropriate
// handler function.
func (w *Watcher) handleEvent(event Event) error {
	w.logger.Debug("got event", "event", event)
	if fn, ok := w.registry.get(event.Path); ok {
		return fn(event)
	}
	if fn, ok := w.registry.get(filepath.Dir(event.Path)); ok {
		return fn(event)
	}

	return nil
}

// watch watches for events from the watcher and calls the appropriate
// handler function. It returns when the watcher is closed or an error occurs.
// It returns an error if an error occurs.
func (w *Watcher) watch() error {
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

// Add adds a path to the watcher and registers a handler function for it.
func (w *Watcher) Add(path string, fn func(Event) error) error {
	if err := w.watcher.Add(path); err != nil {
		return err
	}

	info, err := os.Stat(path)
	if err != nil {
		return err
	}

	// register with the absolute path
	absPath, err := filepath.Abs(path)
	if err != nil {
		return err
	}
	w.registry.register(absPath, fn)

	if !info.IsDir() {
		// w.watcher.Add() doesn't trigger an event for an existing file, so we do it manually
		e := &EventFileInfo{FileInfo: info, name: path}
		w.watcher.TriggerEvent(fw.Create, e)
	}

	return nil
}

// handleManualTriggerEventFn handler function for manual trigger events.
// This is used when a file is added to the watcher manually, and we need
// to register a handler function for it.
func (w *Watcher) handleManualTriggerEventFn(event Event) error {
	path := event.Name()
	absPath, err := filepath.Abs(path)
	if err != nil {
		return err
	}

	if fn, ok := w.registry.get(absPath); ok {
		return fn(event)
	}

	if fn, ok := w.registry.get(path); ok {
		fnAbs := func(event Event) error {
			event.Path = path
			return fn(event)
		}
		w.registry.register(absPath, fnAbs)
		return fnAbs(event)
	}
	return nil
}

func (w *Watcher) Start() {
	// Start the watching process - it'll check for changes every pollingInterval ms.
	go func() {
		if err := w.watcher.Start(pollingInterval); err != nil {
			w.logger.CaptureError("error starting watcher", err)
		}
	}()
	w.watcher.Wait()

	// The first time we see a file, it comes from a manual trigger
	// where event.Path is not defined (it's "-"). So we register a
	// handler function for it here.
	w.registry.register("-", w.handleManualTriggerEventFn)

	w.wg.Add(1)
	go func() {
		w.logger.Debug("starting watcher")
		defer w.wg.Done()
		if err := w.watch(); err != nil {
			w.logger.CaptureError("error watching", err)
		}
	}()
}

func (w *Watcher) Close() {
	w.watcher.Close()
	w.wg.Wait()
	w.registry.clear()
	w.logger.Debug("watcher closed")
}

func (w *Watcher) TriggerEvent(eventType fw.Op, info os.FileInfo) {
	w.watcher.TriggerEvent(eventType, info)
}
