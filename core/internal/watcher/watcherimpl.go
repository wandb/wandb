package watcher

import (
	"path/filepath"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/pkg/observability"
)

type watcher struct {
	sync.Mutex

	logger           *observability.CoreLogger
	pollingStopwatch waiting.StopwatchFactory

	treeWatchers map[string]*treeWatcher
}

func newWatcher(params Params) *watcher {
	if params.PollingStopwatch == nil {
		params.PollingStopwatch = waiting.NewStopwatchFactory(
			500 * time.Millisecond,
		)
	}

	return &watcher{
		logger:           params.Logger,
		pollingStopwatch: params.PollingStopwatch,

		treeWatchers: make(map[string]*treeWatcher),
	}
}

func (w *watcher) Watch(path string, onChange func()) error {
	return w.watch(path, onChange, nil)
}

func (w *watcher) WatchTree(path string, onChange func(string)) error {
	return w.watch(path, nil, onChange)
}

func (w *watcher) watch(
	path string,
	onRootChange func(),
	onChildChange func(string),
) error {
	absPath, err := filepath.Abs(path)
	if err != nil {
		return err
	}

	w.Lock()
	defer w.Unlock()

	treeWatcher := w.treeWatchers[absPath]
	if treeWatcher == nil {
		treeWatcher = NewTreeWatcher(
			absPath,
			w.pollingStopwatch.New(),
		)
		w.treeWatchers[absPath] = treeWatcher
		treeWatcher.Start()
	}

	if onRootChange != nil {
		treeWatcher.AddRootCallback(onRootChange)
	}
	if onChildChange != nil {
		treeWatcher.AddChildCallback(onChildChange)
	}

	return nil
}

func (w *watcher) Finish() {
	stopFns := make([]func(), 0)

	w.Lock()
	for _, treeWatcher := range w.treeWatchers {
		stopFns = append(stopFns, treeWatcher.Stop)
	}
	w.treeWatchers = make(map[string]*treeWatcher)
	w.Unlock()

	// Stop all watchers in parallel.
	wg := &sync.WaitGroup{}
	for _, stop := range stopFns {
		stop := stop
		wg.Add(1)
		go func() {
			stop()
			wg.Done()
		}()
	}
	wg.Wait()
}
