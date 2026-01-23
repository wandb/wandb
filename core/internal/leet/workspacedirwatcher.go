package leet

import (
	"fmt"
	"os"
	"slices"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"golang.org/x/sync/errgroup"
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
		if !strings.HasPrefix(name, "run") && !strings.HasPrefix(name, "offline-run") {
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
	if msg.Err != nil {
		w.logger.CaptureError(fmt.Errorf("workspace: wandb dir scan: %v", msg.Err))
		return w.pollWandbDirCmd(wandbDirPollInterval)
	}

	if !w.runKeysEqual(msg.RunKeys) {
		w.applyRunKeys(msg.RunKeys)
		// preload run overview data in the background.
		go w.preloadRunOverview(msg.RunKeys)
	}

	return w.pollWandbDirCmd(wandbDirPollInterval)
}

func (w *Workspace) preloadRunOverview(runKeys []string) {
	group := &errgroup.Group{}
	group.SetLimit(maxConcurrentPreloads)

	for _, runKey := range runKeys {
		w.roMu.RLock()
		if _, ok := w.runOverview[runKey]; ok {
			continue
		}
		w.roMu.RUnlock()

		group.Go(func() error {
			wandbFile := w.runWandbFile(runKey)
			if wandbFile == "" {
				return nil
			}
			reader, err := NewWandbReader(wandbFile, w.logger)
			if err != nil {
				return nil
			}
			for range maxRecordsToScan {
				record, err := reader.store.Read()
				if err != nil {
					break
				}
				if record == nil {
					continue
				}
				if rr, ok := record.RecordType.(*spb.Record_Run); ok && rr.Run != nil {
					rm := RunMsg{
						ID:          rr.Run.RunId,
						DisplayName: rr.Run.DisplayName,
						Project:     rr.Run.Project,
						Config:      rr.Run.Config,
					}
					ro := w.getOrCreateRunOverview(runKey)
					ro.ProcessRunMsg(rm)
				}
			}
			return nil
		})
	}
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
