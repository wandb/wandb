package runfiles

import (
	"sync"

	"github.com/wandb/wandb/core/internal/waiting"
)

// uploadBatcher helps batch many simultaneous upload operations.
type uploadBatcher struct {
	sync.Mutex

	// Wait group for Add-ed files to get uploaded.
	addWG *sync.WaitGroup

	// Files collected so far.
	files map[string]struct{}

	// Whether an upload is queued to happen soon.
	isQueued bool

	// How long to wait to collect a batch before sending it.
	delay waiting.Delay

	// Callback to upload a list of files.
	upload func([]string)
}

func newUploadBatcher(
	delay waiting.Delay,
	upload func([]string),
) *uploadBatcher {
	if delay == nil {
		delay = waiting.NoDelay()
	}

	return &uploadBatcher{
		addWG: &sync.WaitGroup{},
		files: make(map[string]struct{}),

		delay:  delay,
		upload: upload,
	}
}

// Add adds files to the next upload batch, scheduling one if necessary.
func (b *uploadBatcher) Add(files []string) {
	if b.delay.IsZero() {
		b.upload(files)
		return
	}

	b.Lock()
	defer b.Unlock()

	for _, file := range files {
		b.files[file] = struct{}{}
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
	files := b.files
	b.files = make(map[string]struct{})
	b.Unlock()

	filesSlice := make([]string, 0, len(files))
	for k := range files {
		filesSlice = append(filesSlice, k)
	}

	b.upload(filesSlice)
}
