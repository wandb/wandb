// Copyright 2024 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package transfermanager

import (
	"context"
	"errors"
	"fmt"
	"hash"
	"hash/crc32"
	"io"
	"io/fs"
	"math"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"cloud.google.com/go/storage"
	"github.com/googleapis/gax-go/v2/callctx"
	"google.golang.org/api/iterator"
)

// maxChecksumZeroArraySize is the maximum amount of memory to allocate for
// updating the checksum. A larger size will occupy more memory but will require
// fewer updates when computing the crc32c of a full object (but is not necessarily
// more performant). 100kib is around the smallest size with the highest performance.
const maxChecksumZeroArraySize = 100 * 1024

// Downloader manages a set of parallelized downloads.
type Downloader struct {
	client              *storage.Client
	config              *transferManagerConfig
	inputs              []DownloadObjectInput
	results             []DownloadOutput
	errors              []error
	inputsMu            sync.Mutex
	resultsMu           sync.Mutex
	errorsMu            sync.Mutex
	work                chan *DownloadObjectInput // Piece of work to be executed.
	doneReceivingInputs chan bool                 // Indicates to finish up work; expecting no more inputs.
	workers             *sync.WaitGroup           // Keeps track of the workers that are currently running.
	downloadsInProgress *sync.WaitGroup           // Keeps track of how many objects have completed at least 1 shard, but are waiting on more
}

// DownloadObject queues the download of a single object. This will initiate the
// download but is non-blocking; call Downloader.Results or use the callback to
// process the result. DownloadObject is thread-safe and can be called
// simultaneously from different goroutines.
// The download may not start immediately if all workers are busy, so a deadline
// set on the ctx may time out before the download even starts. To set a timeout
// that starts with the download, use the [WithPerOpTimeout()] option.
func (d *Downloader) DownloadObject(ctx context.Context, input *DownloadObjectInput) error {
	if d.closed() {
		return errors.New("transfermanager: Downloader used after WaitAndClose was called")
	}
	if err := d.validateObjectInput(input); err != nil {
		return err
	}

	input.ctx = ctx
	d.addInput(input)
	return nil
}

// DownloadDirectory queues the download of a set of objects to a local path.
// This will initiate the download but is non-blocking; call Downloader.Results
// or use the callback to process the result. DownloadDirectory is thread-safe
// and can be called simultaneously from different goroutines.
// DownloadDirectory will resolve any filters on the input and create the needed
// directory structure locally. Do not modify this struture until the download
// has completed.
// DownloadDirectory will fail if any of the files it attempts to download
// already exist in the local directory.
func (d *Downloader) DownloadDirectory(ctx context.Context, input *DownloadDirectoryInput) error {
	if d.closed() {
		return errors.New("transfermanager: Downloader used after WaitAndClose was called")
	}
	if err := d.validateDirectoryInput(input); err != nil {
		return err
	}

	query := &storage.Query{
		Prefix:      input.Prefix,
		StartOffset: input.StartOffset,
		EndOffset:   input.EndOffset,
		MatchGlob:   input.MatchGlob,
	}
	if err := query.SetAttrSelection([]string{"Name"}); err != nil {
		return fmt.Errorf("transfermanager: DownloadDirectory query.SetAttrSelection: %w", err)
	}

	// Grab a snapshot of the local directory so we can return to it on error.
	localDirSnapshot := make(map[string]bool) // stores all filepaths to directories in localdir
	if err := filepath.WalkDir(input.LocalDirectory, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			if errors.Is(err, os.ErrNotExist) {
				return nil
			}
			return err
		}
		if d.IsDir() {
			localDirSnapshot[path] = true
		}
		return nil
	}); err != nil {
		return fmt.Errorf("transfermanager: local directory walkthrough failed: %w", err)
	}

	cleanFiles := func(inputs []DownloadObjectInput) error {
		// Remove all created files.
		for _, in := range inputs {
			f := in.Destination.(*os.File)
			f.Close()
			os.Remove(f.Name())
		}

		// Remove all created dirs.
		var removePaths []string
		if err := filepath.WalkDir(input.LocalDirectory, func(path string, d os.DirEntry, err error) error {
			if d.IsDir() && !localDirSnapshot[path] {
				removePaths = append(removePaths, path)
				// We don't need to go into subdirectories, since this directory needs to be removed.
				return filepath.SkipDir
			}
			return err
		}); err != nil {
			return fmt.Errorf("transfermanager: local directory walkthrough failed: %w", err)
		}

		for _, path := range removePaths {
			if err := os.RemoveAll(path); err != nil {
				return fmt.Errorf("transfermanager: failed to remove directory: %w", err)
			}
		}
		return nil
	}

	objectsToQueue := []string{}
	it := d.client.Bucket(input.Bucket).Objects(ctx, query)
	for {
		attrs, err := it.Next()
		if err == iterator.Done {
			break
		}
		if err != nil {
			return fmt.Errorf("transfermanager: DownloadDirectory failed to list objects: %w", err)
		}

		// Check if the file exists.
		fileExists := false

		filePath := filepath.Join(input.LocalDirectory, attrs.Name)
		if _, err := os.Stat(filePath); err == nil {
			fileExists = true
			if !d.config.skipIfExists {
				return fmt.Errorf("transfermanager: failed to create file(%q): %w", filePath, os.ErrExist)
			}
		} else if !errors.Is(err, os.ErrNotExist) {
			// Encountered an error other than file does not exist.
			return fmt.Errorf("transfermanager: failed to create file(%q): %w", filePath, err)
		}

		if !(d.config.skipIfExists && fileExists) {
			objectsToQueue = append(objectsToQueue, attrs.Name)
		}
	}

	outs := make(chan DownloadOutput, len(objectsToQueue))
	inputs := make([]DownloadObjectInput, 0, len(objectsToQueue))
	illegalPathObjects := make([]DownloadObjectInput, 0, len(objectsToQueue))

	for _, object := range objectsToQueue {
		objectWithoutPrefix := object
		if len(input.StripPrefix) > 0 {
			objectWithoutPrefix, _ = strings.CutPrefix(object, input.StripPrefix)
		}

		objDirectory := filepath.Join(input.LocalDirectory, filepath.Dir(objectWithoutPrefix))
		filePath := filepath.Join(input.LocalDirectory, objectWithoutPrefix)

		// Prevent directory traversal attacks.
		isUnder, err := isSubPath(input.LocalDirectory, filePath)
		if err != nil {
			cleanFiles(inputs)
			return fmt.Errorf("transfermanager: DownloadDirectory failed to verify path: %w", err)
		}
		if !isUnder {
			// skipped files will later be added in the results
			illegalPathObjects = append(illegalPathObjects, DownloadObjectInput{
				Bucket:                 input.Bucket,
				Object:                 object,
				Callback:               input.OnObjectDownload,
				ctx:                    ctx,
				directoryObjectOutputs: outs,
				directory:              true,
			})
			continue
		}
		// Make sure all directories in the object path exist.
		err = os.MkdirAll(objDirectory, fs.ModeDir|fs.ModePerm)
		if err != nil {
			cleanFiles(inputs)
			return fmt.Errorf("transfermanager: DownloadDirectory failed to make directory(%q): %w", objDirectory, err)
		}

		// Create file to download to.
		f, fErr := os.Create(filePath)
		if fErr != nil {
			cleanFiles(inputs)
			return fmt.Errorf("transfermanager: DownloadDirectory failed to create file(%q): %w", filePath, fErr)
		}

		inputs = append(inputs, DownloadObjectInput{
			Bucket:                 input.Bucket,
			Object:                 object,
			Destination:            f,
			Callback:               input.OnObjectDownload,
			ctx:                    ctx,
			directory:              true,
			directoryObjectOutputs: outs,
		})
	}

	if d.config.asynchronous {
		d.downloadsInProgress.Add(1)
		allObjectsCount := len(inputs) + len(illegalPathObjects)
		go d.gatherObjectOutputs(input, outs, allObjectsCount)
	}
	d.addNewInputs(inputs)

	for _, file := range illegalPathObjects {
		// the waitgroup is further decremented in addResult method
		d.downloadsInProgress.Add(1)
		d.addResult(&file, &DownloadOutput{
			Bucket:  file.Bucket,
			Object:  file.Object,
			Err:     fmt.Errorf("skipping download of object with unsafe path %q", file.Object),
			skipped: true,
		})
	}
	return nil
}

// WaitAndClose waits for all outstanding downloads to complete and closes the
// Downloader. Adding new downloads after this has been called will cause an error.
//
// WaitAndClose returns all the results of the downloads and an error wrapping
// all errors that were encountered by the Downloader when downloading objects.
// These errors are also returned in the respective DownloadOutput for the
// failing download. The results are not guaranteed to be in any order.
// Results will be empty if using the [WithCallbacks] option. WaitAndClose will
// wait for all callbacks to finish.
func (d *Downloader) WaitAndClose() ([]DownloadOutput, error) {
	errMsg := "transfermanager: at least one error encountered downloading objects:"
	select {
	case <-d.doneReceivingInputs: // this allows users to call WaitAndClose various times
		var err error
		if len(d.errors) > 0 {
			err = fmt.Errorf("%s\n%w", errMsg, errors.Join(d.errors...))
		}
		return d.results, err
	default:
		d.downloadsInProgress.Wait()
		d.doneReceivingInputs <- true
		d.workers.Wait()
		close(d.doneReceivingInputs)

		if len(d.errors) > 0 {
			return d.results, fmt.Errorf("%s\n%w", errMsg, errors.Join(d.errors...))
		}
		return d.results, nil
	}
}

// sendInputsToWorkChan polls the inputs slice until d.done.
// It will send all items in inputs to the d.work chan.
// Once it receives from d.done, it drains the remaining items in the inputs
// (sending them to d.work) and then closes the d.work chan.
func (d *Downloader) sendInputsToWorkChan() {
	for {
		select {
		case <-d.doneReceivingInputs:
			d.drainInput()
			close(d.work)
			return
		default:
			d.drainInput()
		}
	}
}

// drainInput consumes everything in the inputs slice and sends it to the work chan.
// It will block if there are not enough workers to consume every input, until all
// inputs are received on the work chan(ie. they're dispatched to an available worker).
func (d *Downloader) drainInput() {
	for {
		d.inputsMu.Lock()
		if len(d.inputs) < 1 {
			d.inputsMu.Unlock()
			return
		}
		input := d.inputs[0]
		d.inputs = d.inputs[1:]
		d.inputsMu.Unlock()
		d.work <- &input
	}
}

func (d *Downloader) addInput(input *DownloadObjectInput) {
	if input.shard == 0 {
		d.downloadsInProgress.Add(1)
	}
	d.inputsMu.Lock()
	d.inputs = append(d.inputs, *input)
	d.inputsMu.Unlock()
}

// addNewInputs adds a slice of inputs to the downloader.
// This should only be used to queue new objects.
func (d *Downloader) addNewInputs(inputs []DownloadObjectInput) {
	d.downloadsInProgress.Add(len(inputs))

	d.inputsMu.Lock()
	d.inputs = append(d.inputs, inputs...)
	d.inputsMu.Unlock()
}

func (d *Downloader) addResult(input *DownloadObjectInput, result *DownloadOutput) {
	copiedResult := *result // make a copy so that callbacks do not affect the result

	if input.directory && !result.skipped {
		f := input.Destination.(*os.File)
		if err := f.Close(); err != nil && result.Err == nil {
			result.Err = fmt.Errorf("closing file(%q): %w", f.Name(), err)
		}

		// Clean up the file if it failed.
		if result.Err != nil {
			os.Remove(f.Name())
		}
	}
	if input.directory && d.config.asynchronous {
		input.directoryObjectOutputs <- copiedResult
	}

	if d.config.asynchronous || input.directory {
		input.Callback(result)
	}
	if !d.config.asynchronous {
		d.resultsMu.Lock()
		d.results = append(d.results, copiedResult)
		d.resultsMu.Unlock()
	}

	// Track all errors that occurred.
	if result.Err != nil {
		d.error(fmt.Errorf("downloading %q from bucket %q: %w", input.Object, input.Bucket, result.Err))
	}
	d.downloadsInProgress.Done()
}

func (d *Downloader) error(err error) {
	d.errorsMu.Lock()
	d.errors = append(d.errors, err)
	d.errorsMu.Unlock()
}

// downloadWorker continuously processes downloads until the work channel is closed.
func (d *Downloader) downloadWorker() {
	for {
		input, ok := <-d.work
		if !ok {
			break // no more work; exit
		}

		if input.shard == 0 {
			d.startDownload(input)
		} else {
			out := input.downloadShard(d.client, d.config.perOperationTimeout, d.config.partSize)
			// If this isn't the first shard, send to the output channel specific to the object.
			// This should never block since the channel is buffered to exactly the number of shards.
			input.shardOutputs <- out
		}
	}
	d.workers.Done()
}

// startDownload downloads the first shard and schedules subsequent shards
// if necessary.
func (d *Downloader) startDownload(input *DownloadObjectInput) {
	var out *DownloadOutput

	// Full object read. Request the full object and only read partSize bytes
	// (or the full object, if smaller than partSize), so that we can avoid a
	// metadata call to grab the CRC32C for JSON downloads.
	if fullObjectRead(input.Range) {
		input.checkCRC = true
		out = input.downloadFirstShard(d.client, d.config.perOperationTimeout, d.config.partSize)
	} else {
		out = input.downloadShard(d.client, d.config.perOperationTimeout, d.config.partSize)
	}

	if out.Err != nil {
		// Don't queue more shards if the first failed.
		d.addResult(input, out)
		return
	}

	numShards := numShards(out.Attrs, input.Range, d.config.partSize)
	input.checkCRC = input.checkCRC && !out.Attrs.Decompressed // do not checksum if the object was decompressed

	if numShards > 1 {
		outs := d.queueShards(input, out.Attrs.Generation, numShards)
		// Start a goroutine that gathers shards sent to the output
		// channel and adds the result once it has received all shards.
		go d.gatherShards(input, out, outs, numShards, out.crc32c)

	} else {
		// Download completed with a single shard.
		if input.checkCRC {
			if err := checksumObject(out.crc32c, out.Attrs.CRC32C); err != nil {
				out.Err = err
			}
		}
		d.addResult(input, out)
	}
}

// queueShards queues all subsequent shards of an object after the first.
// The results should be forwarded to the returned channel.
func (d *Downloader) queueShards(in *DownloadObjectInput, gen int64, shards int) <-chan *DownloadOutput {
	// Create a channel that can be received from to compile the
	// shard outputs.
	outs := make(chan *DownloadOutput, shards)
	in.shardOutputs = outs

	// Create a shared context that we can cancel if a shard fails.
	in.ctx, in.cancelCtx = context.WithCancelCause(in.ctx)

	// Add generation in case the object changes between calls.
	in.Generation = &gen

	// Queue remaining shards.
	for i := 1; i < shards; i++ {
		newShard := in // this is fine, since the input should only differ in the shard num
		newShard.shard = i
		d.addInput(newShard)
	}

	return outs
}

var errCancelAllShards = errors.New("cancelled because another shard failed")

// gatherShards receives from the given channel exactly (shards-1) times (since
// the first shard should already be complete).
// It will add the result to the Downloader once it has received all shards.
// gatherShards cancels remaining shards if any shard errored.
// It does not do any checking to verify that shards are for the same object.
func (d *Downloader) gatherShards(in *DownloadObjectInput, out *DownloadOutput, outs <-chan *DownloadOutput, shards int, firstPieceCRC uint32) {
	errs := []error{}
	orderedChecksums := make([]crc32cPiece, shards-1)

	for i := 1; i < shards; i++ {
		shardOut := <-outs

		// We can ignore errors that resulted from a previous error.
		// Note that we may still get some cancel errors if they
		// occurred while the operation was already in progress.
		if shardOut.Err != nil && !(errors.Is(shardOut.Err, context.Canceled) && errors.Is(context.Cause(in.ctx), errCancelAllShards)) {
			// If a shard errored, track the error and cancel the shared ctx.
			errs = append(errs, shardOut.Err)
			in.cancelCtx(errCancelAllShards)
			continue
		}
		// Collect remaining checksums starting from second shard.
		if shardOut.shard > 0 && shardOut.shard < shards {
			orderedChecksums[shardOut.shard-1] = crc32cPiece{sum: shardOut.crc32c, length: shardOut.shardLength}
		}
	}

	// All pieces gathered.
	if len(errs) == 0 && in.checkCRC && out.Attrs != nil {
		fullCrc := joinCRC32C(firstPieceCRC, orderedChecksums)
		if err := checksumObject(fullCrc, out.Attrs.CRC32C); err != nil {
			errs = append(errs, err)
		}
	}

	// Prepare output.
	out.Range = in.Range
	if len(errs) != 0 {
		out.Err = fmt.Errorf("download shard errors:\n%w", errors.Join(errs...))
	}
	if out.Attrs != nil {
		out.Attrs.StartOffset = 0
		if in.Range != nil {
			out.Attrs.StartOffset = in.Range.Offset
		}
	}
	d.addResult(in, out)
}

// gatherObjectOutputs receives from the given channel exactly numObjects times.
// It will execute the callback once all object outputs are received.
// It does not do any verification on the outputs nor does it cancel other
// objects on error.
func (d *Downloader) gatherObjectOutputs(in *DownloadDirectoryInput, gatherOuts <-chan DownloadOutput, numObjects int) {
	outs := make([]DownloadOutput, 0, numObjects)
	for i := 0; i < numObjects; i++ {
		obj := <-gatherOuts
		outs = append(outs, obj)
	}

	// All objects have been gathered; execute the callback.
	in.Callback(outs)
	d.downloadsInProgress.Done()
}

func (d *Downloader) validateObjectInput(in *DownloadObjectInput) error {
	if d.config.asynchronous && in.Callback == nil {
		return errors.New("transfermanager: input.Callback must not be nil when the WithCallbacks option is set")
	}
	if !d.config.asynchronous && in.Callback != nil {
		return errors.New("transfermanager: input.Callback must be nil unless the WithCallbacks option is set")
	}
	return nil
}

func (d *Downloader) validateDirectoryInput(in *DownloadDirectoryInput) error {
	if d.config.asynchronous && in.Callback == nil {
		return errors.New("transfermanager: input.Callback must not be nil when the WithCallbacks option is set")
	}
	if !d.config.asynchronous && in.Callback != nil {
		return errors.New("transfermanager: input.Callback must be nil unless the WithCallbacks option is set")
	}
	return nil
}

func (d *Downloader) closed() bool {
	select {
	case <-d.doneReceivingInputs:
		return true
	default:
		return false
	}
}

// NewDownloader creates a new Downloader to add operations to.
// Choice of transport, etc is configured on the client that's passed in.
// The returned Downloader can be shared across goroutines to initiate downloads.
func NewDownloader(c *storage.Client, opts ...Option) (*Downloader, error) {
	d := &Downloader{
		client:              c,
		config:              initTransferManagerConfig(opts...),
		inputs:              []DownloadObjectInput{},
		results:             []DownloadOutput{},
		errors:              []error{},
		work:                make(chan *DownloadObjectInput),
		doneReceivingInputs: make(chan bool),
		workers:             &sync.WaitGroup{},
		downloadsInProgress: &sync.WaitGroup{},
	}

	// Start a polling routine to send work through.
	go d.sendInputsToWorkChan()

	// Start workers.
	for i := 0; i < d.config.numWorkers; i++ {
		d.workers.Add(1)
		go d.downloadWorker()
	}

	return d, nil
}

// DownloadRange specifies the object range.
// If the object's metadata property "Content-Encoding" is set to "gzip" or
// satisfies decompressive transcoding per https://cloud.google.com/storage/docs/transcoding
// that file will be served back whole, regardless of the requested range as
// Google Cloud Storage dictates.
type DownloadRange struct {
	// Offset is the starting offset (inclusive) from with the object is read.
	// If offset is negative, the object is not sharded and is read by a single
	// worker abs(offset) bytes from the end, and length must also be negative
	// to indicate all remaining bytes will be read.
	Offset int64
	// Length is the number of bytes to read.
	// If length is negative or larger than the object size, the object is read
	// until the end.
	Length int64
}

// DownloadObjectInput is the input for a single object to download.
type DownloadObjectInput struct {
	// Bucket is the bucket in GCS to download from. Required.
	Bucket string

	// Object is the object in GCS to download. Required.
	Object string

	// Destination is the WriterAt to which the Downloader will write the object
	// data, such as an [os.File] file handle or a [DownloadBuffer]. Required.
	Destination io.WriterAt

	// Generation, if specified, will request a specific generation of the object.
	// Optional. By default, the latest generation is downloaded.
	Generation *int64

	// Conditions constrains the download to act on a specific
	// generation/metageneration of the object.
	// Optional.
	Conditions *storage.Conditions

	// EncryptionKey will be used to decrypt the object's contents.
	// The encryption key must be a 32-byte AES-256 key.
	// See https://cloud.google.com/storage/docs/encryption for details.
	// Optional.
	EncryptionKey []byte

	// Range specifies the range to read of the object.
	// Optional. If not specified, the entire object will be read.
	Range *DownloadRange

	// Callback will be run once the object is finished downloading. It must be
	// set if and only if the [WithCallbacks] option is set; otherwise, it must
	// not be set.
	// A worker will be used to execute the callback; therefore, it should not
	// be a long-running function. WaitAndClose will wait for all callbacks to
	// finish.
	Callback func(*DownloadOutput)

	ctx                    context.Context
	cancelCtx              context.CancelCauseFunc
	shard                  int // the piece of the object range that should be downloaded
	shardOutputs           chan<- *DownloadOutput
	directory              bool // input was queued by calling DownloadDirectory
	directoryObjectOutputs chan<- DownloadOutput
	checkCRC               bool
}

// downloadShard will read a specific object piece into in.Destination.
// If timeout is less than 0, no timeout is set.
func (in *DownloadObjectInput) downloadShard(client *storage.Client, timeout time.Duration, partSize int64) (out *DownloadOutput) {
	out = &DownloadOutput{Bucket: in.Bucket, Object: in.Object, Range: in.Range}

	objRange := shardRange(in.Range, partSize, in.shard)
	ctx := in.setOptionsOnContext(timeout)
	o := in.setOptionsOnObject(client)

	r, err := o.NewRangeReader(ctx, objRange.Offset, objRange.Length)
	if err != nil {
		out.Err = err
		return
	}

	// Determine the offset this shard should write to.
	offset := objRange.Offset
	if in.Range != nil {
		if in.Range.Offset > 0 {
			offset = objRange.Offset - in.Range.Offset
		} else {
			offset = 0
		}
	}

	var w io.Writer
	w = io.NewOffsetWriter(in.Destination, offset)

	var crcHash hash.Hash32
	if in.checkCRC {
		crcHash = crc32.New(crc32.MakeTable(crc32.Castagnoli))
		w = io.MultiWriter(w, crcHash)
	}

	n, err := io.Copy(w, r)
	if err != nil {
		out.Err = err
		r.Close()
		return
	}

	if err = r.Close(); err != nil {
		out.Err = err
		return
	}

	out.Attrs = &r.Attrs
	out.shard = in.shard
	out.shardLength = n
	if in.checkCRC {
		out.crc32c = crcHash.Sum32()
	}
	return
}

// downloadFirstShard will read the first object piece into in.Destination.
// If timeout is less than 0, no timeout is set.
func (in *DownloadObjectInput) downloadFirstShard(client *storage.Client, timeout time.Duration, partSize int64) (out *DownloadOutput) {
	out = &DownloadOutput{Bucket: in.Bucket, Object: in.Object, Range: in.Range}

	ctx := in.setOptionsOnContext(timeout)
	o := in.setOptionsOnObject(client)

	r, err := o.NewReader(ctx)
	if err != nil {
		out.Err = err
		return
	}

	var w io.Writer
	w = io.NewOffsetWriter(in.Destination, 0)

	var crcHash hash.Hash32
	if in.checkCRC {
		crcHash = crc32.New(crc32.MakeTable(crc32.Castagnoli))
		w = io.MultiWriter(w, crcHash)
	}

	// Copy only the first partSize bytes before closing the reader.
	// If we encounter an EOF, the file was smaller than partSize.
	n, err := io.CopyN(w, r, partSize)
	if err != nil && err != io.EOF {
		out.Err = err
		r.Close()
		return
	}

	if err = r.Close(); err != nil {
		out.Err = err
		return
	}

	out.Attrs = &r.Attrs
	out.shard = in.shard
	out.shardLength = n
	if in.checkCRC {
		out.crc32c = crcHash.Sum32()
	}
	return
}

func (in *DownloadObjectInput) setOptionsOnContext(timeout time.Duration) context.Context {
	ctx := in.ctx
	if timeout > 0 {
		c, cancel := context.WithTimeout(ctx, timeout)
		defer cancel()
		ctx = c
	}

	// The first shard will be sent as download many, since we do not know yet
	// if it will be sharded.
	method := downloadMany
	if in.shard != 0 {
		method = downloadSharded
	}
	return setUsageMetricHeader(ctx, method)
}

func (in *DownloadObjectInput) setOptionsOnObject(client *storage.Client) *storage.ObjectHandle {
	o := client.Bucket(in.Bucket).Object(in.Object)
	if in.Conditions != nil {
		o = o.If(*in.Conditions)
	}
	if in.Generation != nil {
		o = o.Generation(*in.Generation)
	}
	if len(in.EncryptionKey) > 0 {
		o = o.Key(in.EncryptionKey)
	}
	return o
}

// DownloadDirectoryInput is the input for a directory to download.
type DownloadDirectoryInput struct {
	// Bucket is the bucket in GCS to download from. Required.
	Bucket string

	// LocalDirectory specifies the directory to download the matched objects
	// to. Relative paths are allowed. The directory structure and contents
	// must not be modified while the download is in progress.
	// The directory will be created if it does not already exist. Required.
	LocalDirectory string

	// StripPrefix is a prefix to be removed from the path of the local file on
	// download from GCS. For example, if you have an object in GCS called
	// "mydirectory/a/file", and StripPrefix is set to "mydirectory/", the file
	// will be downloaded to "{LocalDirectory}/a/file". Optional.
	StripPrefix string

	// Prefix is the prefix filter to download objects whose names begin with this.
	// Optional.
	Prefix string

	// StartOffset is used to filter results to objects whose names are
	// lexicographically equal to or after startOffset. If endOffset is also
	// set, the objects listed will have names between startOffset (inclusive)
	// and endOffset (exclusive). Optional.
	StartOffset string

	// EndOffset is used to filter results to objects whose names are
	// lexicographically before endOffset. If startOffset is also set, the
	// objects listed will have names between startOffset (inclusive) and
	// endOffset (exclusive). Optional.
	EndOffset string

	// MatchGlob is a glob pattern used to filter results (for example, foo*bar). See
	// https://cloud.google.com/storage/docs/json_api/v1/objects/list#list-object-glob
	// for syntax details. Optional.
	MatchGlob string

	// Callback will run after all the objects in the directory as selected by
	// the provided filters are finished downloading.
	// It must be set if and only if the [WithCallbacks] option is set.
	// WaitAndClose will wait for all callbacks to finish.
	Callback func([]DownloadOutput)

	// OnObjectDownload will run after every finished object download. Optional.
	OnObjectDownload func(*DownloadOutput)
}

// DownloadOutput provides output for a single object download, including all
// errors received while downloading object parts. If the download was successful,
// Attrs will be populated.
type DownloadOutput struct {
	Bucket string
	Object string
	Range  *DownloadRange             // requested range, if it was specified
	Err    error                      // error occurring during download
	Attrs  *storage.ReaderObjectAttrs // attributes of downloaded object, if successful

	skipped     bool
	shard       int
	shardLength int64
	crc32c      uint32
}

// numShards calculates how many shards the given range should be divided into
// given the part size.
func numShards(attrs *storage.ReaderObjectAttrs, r *DownloadRange, partSize int64) int {
	objectSize := attrs.Size

	// Transcoded objects do not support ranged reads.
	if attrs.ContentEncoding == "gzip" {
		return 1
	}

	// Sharding turned off with partSize < 1.
	if partSize < 1 {
		return 1
	}

	// Divide entire object into shards if no range given.
	if r == nil {
		return int(math.Ceil(float64(objectSize) / float64(partSize)))
	}
	// Negative offset reads the whole object in one go.
	if r.Offset < 0 {
		return 1
	}

	firstByte := r.Offset

	// Read to the end of the object, or, if smaller, read only the amount
	// of bytes requested.
	lastByte := min(objectSize-1, r.Offset+r.Length-1)

	// If length is negative, read to the end.
	if r.Length < 0 {
		lastByte = objectSize - 1
	}

	totalBytes := lastByte - firstByte

	return int(totalBytes/partSize) + 1
}

// shardRange calculates the range this shard corresponds to given the
// requested range. Expects the shard to be valid given the range.
func shardRange(r *DownloadRange, partSize int64, shard int) DownloadRange {
	if r == nil {
		// Entire object
		return DownloadRange{
			Offset: int64(shard) * partSize,
			Length: partSize,
		}
	}

	// No sharding if partSize is less than 1.
	if partSize < 1 {
		return *r
	}

	// Negative offset reads the whole object in one go.
	if r.Offset < 0 {
		return *r
	}

	shardOffset := int64(shard)*partSize + r.Offset
	shardLength := partSize // it's ok if we go over the object size

	// If requested bytes end before partSize, length should be smaller.
	if shardOffset+shardLength > r.Offset+r.Length {
		shardLength = r.Offset + r.Length - shardOffset
	}

	return DownloadRange{
		Offset: shardOffset,
		Length: shardLength,
	}
}

const (
	xGoogHeaderKey  = "x-goog-api-client"
	usageMetricKey  = "gccl-gcs-cmd"
	downloadMany    = "tm.download_many"
	downloadSharded = "tm.download_sharded"
)

// Sets invocation ID headers on the context which will be propagated as
// headers in the call to the service (for both gRPC and HTTP).
func setUsageMetricHeader(ctx context.Context, method string) context.Context {
	header := fmt.Sprintf("%s/%s", usageMetricKey, method)
	return callctx.SetHeaders(ctx, xGoogHeaderKey, header)
}

type crc32cPiece struct {
	sum    uint32 // crc32c checksum of the piece
	length int64  // number of bytes in this piece
}

// joinCRC32C pieces together the initial checksum with the orderedChecksums
// provided to calculate the checksum of the whole.
func joinCRC32C(initialChecksum uint32, orderedChecksums []crc32cPiece) uint32 {
	base := initialChecksum

	zeroes := make([]byte, maxChecksumZeroArraySize)
	for _, part := range orderedChecksums {
		// Precondition Base (flip every bit)
		base ^= 0xFFFFFFFF

		// Zero pad base crc32c. To conserve memory, do so with only maxChecksumZeroArraySize
		// at a time. Reuse the zeroes array where possible.
		var padded int64 = 0
		for padded < part.length {
			desiredZeroes := min(part.length-padded, maxChecksumZeroArraySize)
			base = crc32.Update(base, crc32.MakeTable(crc32.Castagnoli), zeroes[:desiredZeroes])
			padded += desiredZeroes
		}

		// Postcondition Base (same as precondition, this switches the bits back)
		base ^= 0xFFFFFFFF

		// Bitwise OR between Base and Part to produce a new Base
		base ^= part.sum
	}
	return base
}

func fullObjectRead(r *DownloadRange) bool {
	return r == nil || (r.Offset == 0 && r.Length < 0)
}

func checksumObject(got, want uint32) error {
	// Only checksum the object if we have a valid CRC32C.
	if want != 0 && want != got {
		return fmt.Errorf("bad CRC on read: got %d, want %d", got, want)
	}
	return nil
}

func isSubPath(localDirectory, filePath string) (bool, error) {
	// Validate if paths can be converted to absolute paths.
	absLocalDirectory, err := filepath.Abs(localDirectory)
	if err != nil {
		return false, fmt.Errorf("cannot convert local directory to absolute path: %w", err)
	}
	absFilePath, err := filepath.Abs(filePath)
	if err != nil {
		return false, fmt.Errorf("cannot convert file path to absolute path: %w", err)
	}

	absFilePathFolder := filepath.Dir(absFilePath)
	// The relative path from the local directory to the final file path's directory.
	// ex 1: if localDirectory is /tmp/foo and filePath is /tmp/foo/bar, rel will be ".".
	// ex 2: if localDirectory is /tmp/foo and filePath is /tmp/bar, rel will be "..".
	rel, err := filepath.Rel(absLocalDirectory, absFilePathFolder)
	if err != nil {
		return false, err
	}

	// rel should not start with ".." to escape target directory
	prevDir := ".." + string(filepath.Separator)
	isUnder := !strings.HasPrefix(rel, prevDir) && rel != ".."

	return isUnder, nil
}
