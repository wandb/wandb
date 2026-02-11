package leet

import (
	"errors"
	"fmt"
	"io"
	"os"
	"slices"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
)

const (
	// TODO: make this configurable.
	wandbDirPollInterval = 5 * time.Second

	// maxRecordsToScan is the maximum number of records to read when searching
	// for the Run record. The Run record is typically one of the first records
	// in a .wandb file.
	maxRecordsToScan = 10

	// maxConcurrentPreloads limits the number of concurrent run record preloads.
	maxConcurrentPreloads = 4
)

var errRunRecordNotFound = errors.New("run record not found")

// runOverviewPreloader implements a bounded-concurrency FIFO queue with dedupe.
type runOverviewPreloader struct {
	pending     map[string]struct{} // queued or in-flight
	inFlight    map[string]struct{}
	queue       []string // FIFO of queued (not in-flight)
	maxInFlight int
}

func newRunOverviewPreloader(maxInFlight int) runOverviewPreloader {
	if maxInFlight <= 0 {
		maxInFlight = 1
	}
	return runOverviewPreloader{
		pending:     make(map[string]struct{}),
		inFlight:    make(map[string]struct{}),
		maxInFlight: maxInFlight,
	}
}

func (p *runOverviewPreloader) Enqueue(runKey string) {
	if runKey == "" {
		return
	}
	if _, ok := p.pending[runKey]; ok {
		return
	}
	p.pending[runKey] = struct{}{}
	p.queue = append(p.queue, runKey)
}

func (p *runOverviewPreloader) DropQueuedNotPresent(present map[string]struct{}) {
	if len(p.queue) == 0 {
		return
	}
	kept := p.queue[:0]
	for _, key := range p.queue {
		if _, ok := present[key]; ok {
			kept = append(kept, key)
			continue
		}
		delete(p.pending, key)
	}
	p.queue = kept
}

func (p *runOverviewPreloader) DequeueStartable() []string {
	available := p.maxInFlight - len(p.inFlight)
	if available <= 0 || len(p.queue) == 0 {
		return nil
	}
	n := min(available, len(p.queue))

	keys := make([]string, 0, n)
	for range n {
		runKey := p.queue[0]
		p.queue = p.queue[1:]
		p.inFlight[runKey] = struct{}{}
		keys = append(keys, runKey)
	}
	return keys
}

func (p *runOverviewPreloader) MarkDone(runKey string) {
	delete(p.inFlight, runKey)
	delete(p.pending, runKey)
}

func (w *Workspace) pollWandbDirCmd(delay time.Duration) tea.Cmd {
	wandbDir := w.wandbDir
	if delay < 0 {
		delay = 0
	}
	return tea.Tick(delay, func(time.Time) tea.Msg {
		runKeys, err := scanWandbRunDirs(wandbDir)
		return WorkspaceRunDirsMsg{RunKeys: runKeys, Err: err}
	})
}

func scanWandbRunDirs(wandbDir string) ([]string, error) {
	if wandbDir == "" {
		return nil, nil
	}

	entries, err := os.ReadDir(wandbDir)
	if err != nil {
		return nil, err
	}

	runKeys := make([]string, 0, len(entries))
	for _, entry := range entries {
		name := entry.Name()
		if !strings.HasPrefix(name, "run-") && !strings.HasPrefix(name, "offline-run-") {
			continue
		}
		runKeys = append(runKeys, name)
	}

	// Sort by timestamp in descending order (most recent first).
	slices.SortFunc(runKeys, func(a, b string) int {
		ta, tb := parseRunDirTimestamp(a), parseRunDirTimestamp(b)
		if c := tb.Compare(ta); c != 0 {
			return c
		}
		return strings.Compare(a, b)
	})

	return runKeys, nil
}

// parseRunDirTimestamp extracts the timestamp from a run folder name.
//
// Expected formats: "run-YYYYMMDD_HHMMSS-runid" or "offline-run-YYYYMMDD_HHMMSS-runid"
// Returns zero time if parsing fails.
func parseRunDirTimestamp(name string) time.Time {
	// Strip prefix to get "YYYYMMDD_HHMMSS-runid"
	var rest string
	if after, ok := strings.CutPrefix(name, "offline-run-"); ok {
		rest = after
	} else if after, ok := strings.CutPrefix(name, "run-"); ok {
		rest = after
	} else {
		return time.Time{}
	}

	if len(rest) < 15 {
		return time.Time{}
	}

	t, err := time.Parse("20060102_150405", rest[:15])
	if err != nil {
		return time.Time{}
	}
	return t
}

func (w *Workspace) handleWorkspaceRunDirs(msg WorkspaceRunDirsMsg) tea.Cmd {
	pollCmd := w.pollWandbDirCmd(wandbDirPollInterval)

	if msg.Err != nil {
		w.logger.CaptureError(fmt.Errorf("workspace: wandb dir scan: %v", msg.Err))
		return pollCmd
	}

	var selectLatestCmd tea.Cmd
	if !w.runKeysEqual(msg.RunKeys) {
		w.applyRunKeys(msg.RunKeys)
		// Auto-select the latest run on initial workspace load.
		w.autoSelectLatestRunOnLoad.Do(
			func() { selectLatestCmd = w.toggleRunSelected(msg.RunKeys[0]) })
	}
	// Enqueue missing run overviews (even if the run list is unchanged).
	// This makes new run overviews eventually consistent even if the .wandb file
	// wasn't readable on the first scan.
	w.enqueueMissingRunOverviews(msg.RunKeys)

	startCmd := w.startRunOverviewPreloadsCmd()
	if startCmd == nil {
		return pollCmd
	}
	return tea.Batch(pollCmd, startCmd, selectLatestCmd)
}

// enqueueMissingRunOverviews queues runs that don't yet have overview state and
// aren't already queued/in-flight.
func (w *Workspace) enqueueMissingRunOverviews(runKeys []string) {
	for _, runKey := range runKeys {
		if _, ok := w.runOverview[runKey]; ok {
			continue
		}
		w.overviewPreloader.Enqueue(runKey)
	}
}

// startRunOverviewPreloadsCmd starts as many overview preloads as allowed by the
// concurrency limit and returns a batch cmd. It is safe to call repeatedly.
func (w *Workspace) startRunOverviewPreloadsCmd() tea.Cmd {
	runKeys := w.overviewPreloader.DequeueStartable()
	if len(runKeys) == 0 {
		return nil
	}
	cmds := make([]tea.Cmd, 0, len(runKeys))
	for _, runKey := range runKeys {
		cmds = append(cmds, w.preloadRunOverviewCmd(runKey))
	}
	return tea.Batch(cmds...)
}

// preloadRunOverviewCmd reads up to maxRecordsToScan records looking for the Run record.
// It returns a completion msg (success or failure) so the queue can make progress.
func (w *Workspace) preloadRunOverviewCmd(runKey string) tea.Cmd {
	wandbFile := runWandbFile(w.wandbDir, runKey)
	logger := w.logger

	return func() tea.Msg {
		if runKey == "" || wandbFile == "" {
			return WorkspaceRunOverviewPreloadedMsg{
				RunKey: runKey, Err: errRunRecordNotFound}
		}

		reader, err := NewWandbReader(wandbFile, logger)
		if err != nil {
			return WorkspaceRunOverviewPreloadedMsg{RunKey: runKey, Err: err}
		}
		defer reader.Close()

		for range maxRecordsToScan {
			msg, err := reader.ReadNext()
			if err != nil {
				if errors.Is(err, io.EOF) {
					break
				}
				return WorkspaceRunOverviewPreloadedMsg{RunKey: runKey, Err: err}
			}
			if rm, ok := msg.(RunMsg); ok && rm.ID != "" {
				return WorkspaceRunOverviewPreloadedMsg{RunKey: runKey, Run: rm}
			}
		}

		return WorkspaceRunOverviewPreloadedMsg{RunKey: runKey, Err: errRunRecordNotFound}
	}
}

func (w *Workspace) handleWorkspaceRunOverviewPreloaded(
	msg WorkspaceRunOverviewPreloadedMsg,
) tea.Cmd {
	w.overviewPreloader.MarkDone(msg.RunKey)

	if msg.Err == nil && msg.Run.ID != "" {
		ro := w.getOrCreateRunOverview(msg.RunKey)
		ro.ProcessRunMsg(msg.Run)
		// We don't know the final state of this run after a pre-load.
		ro.SetRunState(RunStateUnknown)
	} else if msg.Err != nil && !errors.Is(msg.Err, errRunRecordNotFound) && !os.IsNotExist(msg.Err) {
		// Best-effort logging for unexpected failures; avoid spamming for
		// "file not ready yet" or missing run records.
		err := fmt.Errorf("workspace: preload run overview for %s: %v", msg.RunKey, msg.Err)
		w.logger.CaptureError(err)
	}

	// Keep draining the queue.
	return w.startRunOverviewPreloadsCmd()
}

func (w *Workspace) runKeysEqual(runKeys []string) bool {
	if len(runKeys) != len(w.runs.Items) {
		return false
	}
	for i, key := range runKeys {
		if w.runs.Items[i].Key != key {
			return false
		}
	}
	return true
}

func (w *Workspace) applyRunKeys(runKeys []string) {
	// Preserve the currently highlighted run key if possible.
	prevCursorKey := ""
	if cur, ok := w.runs.CurrentItem(); ok {
		prevCursorKey = cur.Key
	}

	present := make(map[string]struct{}, len(runKeys))
	for _, key := range runKeys {
		present[key] = struct{}{}
	}

	// Drop queued (not in-flight) overview preloads for runs that disappeared.
	w.overviewPreloader.DropQueuedNotPresent(present)

	// If the pinned run disappeared, clear it.
	if w.pinnedRun != "" {
		if _, ok := present[w.pinnedRun]; !ok {
			w.pinnedRun = ""
		}
	}

	// If a selected run disappeared, deselect it and cleanup state.
	for key := range w.selectedRuns {
		if _, ok := present[key]; ok {
			continue
		}
		w.dropRun(key)
	}

	// Defensive cleanup: drop any loaded run that no longer exists.
	for key := range w.runsByKey {
		if _, ok := present[key]; ok {
			continue
		}
		w.dropRun(key)
	}

	w.setRunItems(runKeys)

	if prevCursorKey != "" {
		w.restoreRunCursor(prevCursorKey)
	}
	w.syncRunsPage()
}

func (w *Workspace) setRunItems(runKeys []string) {
	items := w.runs.Items[:0]
	for _, key := range runKeys {
		items = append(items, KeyValuePair{Key: key})
	}
	w.runs.Items = items

	// TODO: wire up filter for the run selector.
	if w.filter.Query() == "" && !w.filter.IsActive() {
		w.runs.FilteredItems = items
		return
	}

	matcher := w.filter.Matcher()
	filtered := make([]KeyValuePair, 0, len(items))
	for _, it := range items {
		if matcher(it.Key) {
			filtered = append(filtered, it)
		}
	}
	w.runs.FilteredItems = filtered
}

func (w *Workspace) restoreRunCursor(runKey string) {
	if runKey == "" || w.runs.ItemsPerPage() <= 0 {
		return
	}
	for idx, it := range w.runs.FilteredItems {
		if it.Key != runKey {
			continue
		}
		page := idx / w.runs.ItemsPerPage()
		line := idx % w.runs.ItemsPerPage()
		w.runs.SetPageAndLine(page, line)
		return
	}
}
