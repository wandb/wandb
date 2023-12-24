package watcher

import (
	"os"
	"path/filepath"
	"sync"

	fw "github.com/radovskyb/watcher"
	"github.com/wandb/wandb/core/pkg/observability"
)

type WatcherService struct {
	watcher  *fw.Watcher
	wg       *sync.WaitGroup
	logger   *observability.CoreLogger
	registry *registry
}

type WatcherServiceOption func(*WatcherService)

func WithLogger(logger *observability.CoreLogger) WatcherServiceOption {
	return func(w *WatcherService) {
		w.logger = logger
	}
}

func New(opts ...WatcherServiceOption) *WatcherService {
	w := &WatcherService{
		watcher: fw.New(),
		wg:      &sync.WaitGroup{},
	}
	for _, opt := range opts {
		opt(w)
	}
	return w
}

func (w *WatcherService) handleEvent(event fw.Event) error {
	w.logger.Debug("got event", "event", event)
	if fn, ok := w.registry.events[event.Path]; ok {
		return fn(event)
	}
	return nil
}

func (w *WatcherService) watch() error {
	w.logger.Debug("starting watcher")
	for {
		select {
		case event := <-w.watcher.Event:
			w.logger.Debug("got event", "event", event)
			err := w.handleEvent(event)
			if err != nil {
				w.logger.CaptureError("error handling event", err, "event", event)
				return err
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

func (w *WatcherService) manualTriggerEvent(event fw.Event) error {
	path := event.Name()
	absPath, err := filepath.Abs(path)
	if err != nil {
		return err
	}

	if fn, ok := w.registry.events[absPath]; ok {
		return fn(event)
	}

	if fn, ok := w.registry.events[path]; ok {
		fnAbs := func(event fw.Event) error {
			event.Path = path
			return fn(event)
		}
		w.registry.register(absPath, fnAbs)
		return fnAbs(event)
	}
	return nil
}

func (w *WatcherService) Start() error {
	w.registry.register("-", w.manualTriggerEvent)

	w.wg.Add(1)
	go func() {
		w.logger.Debug("starting watcher")
		defer w.wg.Done()
		err := w.watch()
		if err != nil {
			w.logger.CaptureError("error watching", err)
		}
	}()

	// Start the watching process - it'll check for changes every pollingInterval ms.
	go func() {
		if err := w.watcher.Start(pollingInterval); err != nil {
			w.logger.CaptureError("error starting watcher", err)
		}
	}()
	w.watcher.Wait()
	return nil
}

func (w *WatcherService) Close() {
	w.watcher.Close()
	w.wg.Wait()
	w.logger.Debug("watcher closed")
}

func (w *WatcherService) Add(path string, fn func(fw.Event) error) error {
	if err := w.watcher.Add(path); err != nil {
		return err
	}
	info, err := os.Stat(path)
	if err != nil {
		return err
	}
	if !info.IsDir() {
		// w.watcher.Add() doesn't trigger an event for an existing file, so we do it manually
		e := &EventFileInfo{FileInfo: info, name: path}
		w.watcher.TriggerEvent(fw.Create, e)
	}
	w.registry.register(path, fn)

	return nil
}

type registry struct {
	events map[string]func(fw.Event) error
}

func (r *registry) register(name string, fn func(fw.Event) error) {
	r.events[name] = fn
}
