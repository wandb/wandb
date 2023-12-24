package watcher

import (
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
		return fn()
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

func (w *WatcherService) Start() error {
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

func (w *WatcherService) Add(path string, fn func() error) error {
	if err := w.watcher.Add(path); err != nil {
		return err
	}
	w.registry.register(path, fn)

	return nil
}

type registry struct {
	events map[string]func() error
}

func (r *registry) register(name string, fn func() error) {
	r.events[name] = fn
}
