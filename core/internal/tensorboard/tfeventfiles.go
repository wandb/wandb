package tensorboard

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"

	"github.com/wandb/wandb/core/internal/paths"
)

// nextTFEventsFile returns the tfevents file that comes after the given one.
//
// TensorBoard stores events across multiple tfevents files. It starts the next
// file after it finishes writing to the previous one, and the files are meant
// to be read in order.
//
// This function takes a directory `dir` containing tfevents files and returns
// the first path matching `filter` that's ordered after `path`. If `path` is "",
// then the first (according to the order) matching path is returned. If the
// next file does not exist, then an empty string is returned.
//
// This returns an error if the directory doesn't exist.
func nextTFEventsFile(
	dir paths.AbsolutePath,
	path *paths.AbsolutePath,
	filter TFEventsFileFilter,
) (*paths.AbsolutePath, error) {
	name := []rune(filepath.Base(path.OrEmpty()))

	entries, err := os.ReadDir(string(dir))
	if err != nil {
		return nil, err
	}

	if len(entries) == 0 {
		return nil, fmt.Errorf("tensorboard: directory is empty")
	}

	next := ""
	for _, entry := range entries {
		// TensorBoard sorts files using Python string comparison:
		// https://github.com/tensorflow/tensorboard/blob/ae7d0b9250f5986dd0f0c238fcaf3c8d7f4312ca/tensorboard/backend/event_processing/directory_watcher.py#L208-L212
		//
		// Python uses Unicode code point numbers when comparing strings:
		// https://docs.python.org/3/tutorial/datastructures.html#comparing-sequences-and-other-types
		//
		// It's not clear whether Go's < operator for strings compares runes
		// (Unicode code points) or bytes, but strings are able to hold
		// arbitrary bytes, so we explictly compare runes here.
		//
		// In practice it's not clear this will matter, since tfevents file
		// names are probably ASCII other than the "hostname" portion which
		// could be arbitrary.
		if slices.Compare([]rune(entry.Name()), name) <= 0 {
			continue
		}

		if next != "" && slices.Compare([]rune(entry.Name()), []rune(next)) >= 0 {
			continue
		}

		if !filter.Matches(entry.Name()) {
			continue
		}

		next = entry.Name()
	}

	if next == "" {
		return nil, nil
	}

	return paths.Absolute(filepath.Join(string(dir), next))
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

// Matches returns whether the path is accepted by the filter.
func (f TFEventsFileFilter) Matches(path string) bool {
	name := filepath.Base(path)

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
