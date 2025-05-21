package tensorboard

import (
	"context"
	"fmt"
	"io"
	"regexp"
	"slices"
	"strconv"
	"strings"

	"gocloud.dev/blob"
)

// nextTFEventsFile returns the tfevents file that comes after the given one.
//
// TensorBoard stores events across multiple tfevents files. It starts the next
// file after it finishes writing to the previous one, and the files are meant
// to be read in order.
//
// This function works with local filesystems as well as cloud storage.
// In both cases, a prefixed bucket is used to represent a directory.
//
// Returns the key of the first object in the bucket that's ordered after
// `lastFile` and whose key matches `filter`. If `lastFile` is "", then the
// first matching key is returned. If there is no next object, an empty string
// is returned.
//
// Returns an error if the directory doesn't exist or if a network error
// prevents iterating over it.
func nextTFEventsFile(
	ctx context.Context,
	bucket *blob.Bucket,
	lastFile string,
	filter TFEventsFileFilter,
) (string, error) {
	lastFileRunes := []rune(lastFile)

	// bucket.List() returns values in lexicographical order of UTF-8 encoded
	// keys.
	//
	// TensorBoard sorts files using Python string comparison:
	// https://github.com/tensorflow/tensorboard/blob/ae7d0b9250f5986dd0f0c238fcaf3c8d7f4312ca/tensorboard/backend/event_processing/directory_watcher.py#L208-L212
	//
	// Python uses Unicode code point numbers when comparing strings.
	// https://docs.python.org/3/tutorial/datastructures.html#comparing-sequences-and-other-types
	//
	// Lexicographically sorting UTF-32 strings (i.e. Unicode code points)
	// and UTF-8 strings produces the same result, so these are the same.
	sortedEntries := bucket.List(nil)

	for {
		obj, err := sortedEntries.Next(ctx)

		if err == io.EOF {
			return "", nil
		}

		if err != nil {
			return "", fmt.Errorf("tensorboard: nextTFEventsFile: %v", err)
		}

		// It's not clear whether Go's < operator for strings compares runes
		// (Unicode code points) or bytes, but strings are able to hold
		// arbitrary bytes, so we explicitly compare runes here.
		//
		// In practice it's not clear this will matter, since tfevents file
		// names are probably ASCII other than the "hostname" portion which
		// could be arbitrary.
		if slices.Compare([]rune(obj.Key), lastFileRunes) > 0 &&
			filter.Matches(obj.Key) {
			return obj.Key, nil
		}
	}
}

// TFEventsFileFilter is the information necessary to select related
// tfevents files.
type TFEventsFileFilter struct {
	// StartTimeSec is the minimum start time expressed in Unix epoch seconds.
	//
	// tfevents filenames include a start time. We use this to determine
	// whether a file was generated as part of the current run or in a
	// previous run.
	StartTimeSec int64

	// Hostname is the exact hostname to expect.
	//
	// tfevents filenames include the Hostname (output of HOSTNAME(1)) of the
	// machine that wrote them. This is an important filter in case tfevents
	// files are located in a shared directory.
	Hostname string
}

// Matches returns whether the tfevents file name is accepted by the filter.
func (f TFEventsFileFilter) Matches(name string) bool {
	switch {
	// The TensorFlow profiler creates an empty tfevents file with this suffix.
	case strings.HasSuffix(name, ".profile-empty"):
		return false

	// Amazon SageMaker creates temporary tfevents files with the suffix
	// .sagemaker-uploaded which we don't want to upload.
	case strings.HasSuffix(name, ".sagemaker-uploaded"):
		return false
	}

	// We expect a filename containing
	//    tfevents.<time>.<hostname>
	//
	// TensorBoard format: https://github.com/tensorflow/tensorboard/blob/f3f26b46981da5bd46a5bb93fcf02d9eb7608bc1/tensorboard/summary/writer/event_file_writer.py#L81
	// TensorFlow format: https://github.com/tensorflow/tensorflow/blob/8f597046dc30c14b5413813d02c0e0aed399c177/tensorflow/core/util/events_writer.cc#L68
	//
	// The <time> is a time in seconds that's related to when the events file
	// was created---a TensorBoard logs directory can accumulate files each
	// time the user runs their script, and we don't want to associate files
	// from before the run with this run.
	//
	// The <hostname> is exactly as reported through HOSTNAME(1) on the machine
	// writing the file. A logs directory may be in the cloud or on some remote
	// filesystem and written to by multiple machines. Only files created on our
	// same machine are relevant to the run.
	//
	// As one might expect, these heuristics aren't perfect. For example, a user
	// might run multiple TB processes simultaneously, in which case there will
	// be files with the correct <time> and <hostname> that aren't related to
	// this run. It's also not clear whether <hostname> ever needs to be escaped.
	// And of course this could break with a future version of TB.
	re, err := regexp.Compile(
		fmt.Sprintf(
			`tfevents\.(\d+)\.%v`,
			regexp.QuoteMeta(f.Hostname),
		),
	)
	if err != nil {
		panic(err)
	}

	matches := re.FindStringSubmatch(name)
	if matches == nil {
		return false
	}

	tfeventsTime, err := strconv.ParseInt(matches[1], 10, 64)
	if err != nil {
		return false
	}

	return tfeventsTime >= f.StartTimeSec
}
