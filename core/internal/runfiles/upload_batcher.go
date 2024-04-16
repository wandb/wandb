package runfiles

import (
	"sync"
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

	// A function that returns a stream that is signalled when the next
	// batch upload should happen.
	delayFunc func() <-chan struct{}

	// Callback to upload a list of files.
	upload func([]string)
}

func newUploadBatcher(
	delayFunc func() <-chan struct{},
	upload func([]string),
) *uploadBatcher {
	return &uploadBatcher{
		addWG: &sync.WaitGroup{},
		files: make(map[string]struct{}),

		delayFunc: delayFunc,
		upload:    upload,
	}
}

// Add adds files to the next upload batch, scheduling one if necessary.
func (b *uploadBatcher) Add(files []string) {
	if b.delayFunc == nil {
		b.upload(files)
		return
	}

	b.Lock()
	defer b.Unlock()

	for _, file := range files {
		b.files[file] = struct{}{}
	}

	if !b.isQueued {
		b.addWG.Add(1)
		b.isQueued = true

		go b.uploadAfterDelay()
	}
}

// Wait blocks until all files from previous Add calls are uploaded.
func (b *uploadBatcher) Wait() {
	b.addWG.Wait()
}

func (b *uploadBatcher) uploadAfterDelay() {
	<-b.delayFunc()

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

	b.addWG.Done()
}
