package runfiles

import (
	"sync"

	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/waiting"
)

// uploadBatcher helps batch many simultaneous upload operations.
type uploadBatcher struct {
	mu sync.Mutex

	// uploadMu is held to cut and upload a batch.
	uploadMu sync.Mutex

	// done is closed when Wait is called to stop batching.
	done chan struct{}

	// Wait group for Add-ed files to get uploaded.
	addWG *sync.WaitGroup

	// Files collected so far.
	runPaths map[paths.RelativePath]struct{}

	// Whether an upload is queued to happen soon.
	isQueued bool

	// How long to wait to collect a batch before sending it.
	delay waiting.Delay

	// Callback to upload a list of files.
	upload func([]paths.RelativePath)
}

func newUploadBatcher(
	delay waiting.Delay,
	upload func([]paths.RelativePath),
) *uploadBatcher {
	if delay == nil {
		delay = waiting.NoDelay()
	}

	return &uploadBatcher{
		done:     make(chan struct{}),
		addWG:    &sync.WaitGroup{},
		runPaths: make(map[paths.RelativePath]struct{}),

		delay:  delay,
		upload: upload,
	}
}

// Add adds files to the next upload batch, scheduling one if necessary.
func (b *uploadBatcher) Add(runPaths []paths.RelativePath) {
	if b.delay.IsZero() {
		b.upload(runPaths)
		return
	}

	b.mu.Lock()
	defer b.mu.Unlock()

	for _, runPath := range runPaths {
		b.runPaths[runPath] = struct{}{}
	}

	if !b.isQueued {
		b.isQueued = true

		b.addWG.Add(1)
		go func() {
			defer b.addWG.Done()

			delay, cancelDelay := b.delay.Wait()

			select {
			case <-delay:
			case <-b.done:
				cancelDelay()
			}

			b.uploadBatch()
		}()
	}
}

// Close stops batching and flushes any Add calls.
//
// Unlike Wait, it may only be called once.
func (b *uploadBatcher) Close() {
	close(b.done)
}

// Wait blocks until all files from previous Add calls are uploaded.
func (b *uploadBatcher) Wait() {
	b.addWG.Wait()
}

func (b *uploadBatcher) uploadBatch() {
	// Block and keep batching until the previous batch goes through.
	b.uploadMu.Lock()
	defer b.uploadMu.Unlock()

	// Cut the batch.
	b.mu.Lock()
	b.isQueued = false
	runPathsSet := b.runPaths
	b.runPaths = make(map[paths.RelativePath]struct{})
	b.mu.Unlock()

	runPaths := make([]paths.RelativePath, 0, len(runPathsSet))
	for runPath := range runPathsSet {
		runPaths = append(runPaths, runPath)
	}

	b.upload(runPaths)
}
