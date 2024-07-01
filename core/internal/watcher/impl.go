package watcher

import (
	"context"
	"fmt"
	"path/filepath"
	"sync"
	"time"

	poller "github.com/radovskyb/watcher"
	"github.com/wandb/wandb/core/pkg/observability"
	"golang.org/x/sync/errgroup"
)

type watcher struct {
	sync.Mutex
	logger     *observability.CoreLogger
	delegate   *poller.Watcher
	wg         *sync.WaitGroup
	handlers   map[string]func(string)
	isFinished bool

	pollingPeriod time.Duration
}

func newWatcher(params Params) *watcher {
	if params.PollingPeriod == 0 {
		params.PollingPeriod = 500 * time.Millisecond
	}

	return &watcher{
		logger:   params.Logger,
		wg:       &sync.WaitGroup{},
		handlers: make(map[string]func(string)),

		pollingPeriod: params.PollingPeriod,
	}
}

func (w *watcher) Watch(path string, onChange func()) error {
	return w.watchFileOrDir(path, func(string) { onChange() })
}

func (w *watcher) WatchDir(path string, onChange func(string)) error {
	return w.watchFileOrDir(path, onChange)
}

func (w *watcher) watchFileOrDir(path string, onChange func(string)) error {
	w.Lock()
	defer w.Unlock()

	if w.isFinished {
		return fmt.Errorf("watcher: tried to call Watch() after Finish()")
	}

	if w.delegate == nil {
		if err := w.startWatcher(); err != nil {
			return err
		}
	}

	if err := w.delegate.Add(path); err != nil {
		return err
	}
	w.handlers[path] = onChange

	return nil
}

func (w *watcher) Finish() {
	var delegate *poller.Watcher

	w.Lock()
	w.isFinished = true
	delegate = w.delegate
	w.Unlock()

	if delegate != nil {
		delegate.Close()
	}
	w.wg.Wait()
}

func (w *watcher) startWatcher() error {
	if w.delegate != nil {
		return fmt.Errorf(
			"watcher: tried to start watcher, but it is already started",
		)
	}

	w.delegate = poller.New()
	// NOTE: The "radovskyb/watcher" dependency has a bug where it sometimes
	// emits 'Create' events for files that already exist because of a race
	// condition between Add() and the polling loop in Start().
	//
	// In other words, we cannot distinguish between Write and Create events,
	// which is why that's not part of this package's public interface.
	w.delegate.FilterOps(poller.Write, poller.Create)

	grp, ctx := errgroup.WithContext(context.Background())
	w.wg.Add(2)

	grp.Go(func() error {
		defer w.wg.Done()

		w.loopWatchFiles(ctx)

		return nil
	})

	grp.Go(func() error {
		defer w.wg.Done()

		if err := w.delegate.Start(w.pollingPeriod); err != nil {
			return err
		}

		return nil
	})

	// We want to guarantee at this point that either:
	//   1. Watcher.Start() is successfully looping
	//   2. Watcher.Start() returned an error
	// Until this, Watcher.Close() is a no-op! If Finish() is called too
	// quickly, it will get stuck waiting on the wg because Watcher.Close()
	// wouldn't have stopped the above goroutines.
	watcherStarted := make(chan struct{})
	go func() {
		w.delegate.Wait()
		watcherStarted <- struct{}{}
	}()
	select {
	case <-watcherStarted:
	case <-ctx.Done():
		// This returns the error that caused the context to get canceled.
		return grp.Wait()
	}

	return nil
}

// Loops and processes file events.
//
// 'ctx' is used to break the loop in case the watcher fails to even
// start, in which case none of its channels will ever receive a message.
func (w *watcher) loopWatchFiles(ctx context.Context) {
	for {
		select {
		case event := <-w.delegate.Event:
			if event.IsDir() {
				continue
			}

			if event.Op != poller.Write && event.Op != poller.Create {
				continue
			}

			w.onChange(event)

		case err := <-w.delegate.Error:
			w.logger.CaptureError(
				fmt.Errorf(
					"watcher: error in file watcher: %v",
					err,
				))

		case <-w.delegate.Closed:
			return

		case <-ctx.Done():
			return
		}
	}
}

func (w *watcher) onChange(evt poller.Event) {
	w.Lock()
	handler := w.handlers[evt.Path]
	parentHandler := w.handlers[filepath.Dir(evt.Path)]
	w.Unlock()

	if handler != nil {
		handler(evt.Path)
	} else if parentHandler != nil {
		parentHandler(evt.Path)
	}

	// This shouldn't happen since we don't remove handlers,
	// but we should fail gracefully just in case.
}
