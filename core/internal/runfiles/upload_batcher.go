package runfiles

import (
	"sync"

	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/waiting"
)

// uploadBatcher helps batch many simultaneous upload operations.
type uploadBatcher struct {
	sync.Mutex

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

	b.Lock()
	defer b.Unlock()

	for _, runPath := range runPaths {
		b.runPaths[runPath] = struct{}{}
	}

	if !b.isQueued {
		b.isQueued = true

		b.addWG.Add(1)
		go func() {
			defer b.addWG.Done()
			<-b.delay.Wait()
			b.uploadBatch()
		}()
	}
}

// Wait blocks until all files from previous Add calls are uploaded.
func (b *uploadBatcher) Wait() {
	b.addWG.Wait()
}

func (b *uploadBatcher) uploadBatch() {
	b.Lock()
	b.isQueued = false
	runPathsSet := b.runPaths
	b.runPaths = make(map[paths.RelativePath]struct{})
	b.Unlock()

	runPaths := make([]paths.RelativePath, 0, len(runPathsSet))
	for runPath := range runPathsSet {
		runPaths = append(runPaths, runPath)
	}

	b.upload(runPaths)
}
