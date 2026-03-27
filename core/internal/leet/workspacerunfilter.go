package leet

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	tea "charm.land/bubbletea/v2"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// handleRunFilterKey updates the runs filter draft and reapplies it for live
// preview while the editor is active.
func (w *Workspace) handleRunFilterKey(msg tea.KeyPressMsg) {
	if w.filter.HandleKey(msg) {
		w.applyRunFilter()
	}
}

// handleEnterRunsFilter focuses the runs sidebar and enters runs filter input
// mode. If the sidebar is currently collapsed, it is expanded first.
func (w *Workspace) handleEnterRunsFilter(msg tea.KeyPressMsg) tea.Cmd {
	var cmd tea.Cmd
	if !w.runsAnimState.IsExpanded() && !w.runsAnimState.IsAnimating() {
		cmd = w.handleToggleRunsSidebar(msg)
	}

	w.runs.Active = true
	w.consoleLogsPane.SetActive(false)
	w.runOverviewSidebar.deactivateAllSections()
	w.filter.Activate()
	w.applyRunFilter()

	return cmd
}

// handleClearRunsFilter clears the applied runs filter and exits filter mode.
func (w *Workspace) handleClearRunsFilter(tea.KeyPressMsg) tea.Cmd {
	if w.filter.Query() == "" && !w.filter.IsActive() {
		return nil
	}
	w.filter.Clear()
	w.applyRunFilter()
	return nil
}

// buildRunsFilterStatus returns the status bar prompt for the runs filter.
func (w *Workspace) buildRunsFilterStatus() string {
	return fmt.Sprintf(
		"Runs filter (%s): %s%s [%d/%d] (Enter to apply • Tab to toggle mode)",
		w.filter.Mode().String(),
		w.filter.Query(),
		string(mediumShadeBlock),
		len(w.runs.FilteredItems),
		len(w.runs.Items),
	)
}

// applyRunFilter reevaluates the runs sidebar against the current filter query.
// It preserves the cursor when the previously focused run remains visible.
func (w *Workspace) applyRunFilter() {
	prevCursorKey := ""
	if cur, ok := w.runs.CurrentItem(); ok {
		prevCursorKey = cur.Key
	}

	query := w.filter.Query()
	if query == "" {
		w.runs.FilteredItems = w.runs.Items
	} else {
		compiled := CompileRunFilterQuery(query, w.filter.Mode())
		filtered := make([]KeyValuePair, 0, len(w.runs.Items))
		for _, item := range w.runs.Items {
			if compiled.Match(w.runFilterData(item.Key)) {
				filtered = append(filtered, item)
			}
		}
		w.runs.FilteredItems = filtered
	}

	if prevCursorKey != "" {
		w.restoreRunCursor(prevCursorKey)
	}
	w.syncRunsPage()
}

// runFilterData returns indexed filter metadata for runKey.
//
// If the run has not been preloaded yet, it falls back to the run key so
// name-based filtering still works before richer metadata arrives.
func (w *Workspace) runFilterData(runKey string) WorkspaceRunFilterData {
	data, ok := w.runsFilterIndex[runKey]
	if ok {
		return data
	}
	return WorkspaceRunFilterData{RunKey: runKey}
}

// indexRunFilterData caches searchable metadata derived from a RunMsg.
//
// Run preload and streaming can deliver partial records, so missing fields keep
// the previously indexed value instead of clobbering it.
func (w *Workspace) indexRunFilterData(runKey string, msg RunMsg) {
	data := buildWorkspaceRunFilterData(runKey, msg)
	if existing, ok := w.runsFilterIndex[runKey]; ok {
		if data.DisplayName == "" {
			data.DisplayName = existing.DisplayName
		}
		if data.ID == "" {
			data.ID = existing.ID
		}
		if data.Project == "" {
			data.Project = existing.Project
		}
		if data.Notes == "" {
			data.Notes = existing.Notes
		}
		if len(data.Tags) == 0 && len(existing.Tags) > 0 {
			data.Tags = append([]string(nil), existing.Tags...)
		}
		if len(data.ConfigEntries) == 0 && len(existing.ConfigEntries) > 0 {
			data.ConfigByPath = existing.ConfigByPath
			data.ConfigEntries = existing.ConfigEntries
		}
	}
	w.runsFilterIndex[runKey] = data
}

// buildWorkspaceRunFilterData converts a RunMsg into the indexed metadata used
// by the runs filter.
func buildWorkspaceRunFilterData(runKey string, msg RunMsg) WorkspaceRunFilterData {
	configByPath, configEntries := flattenRunFilterConfig(msg.Config)
	if configByPath == nil {
		configByPath = make(map[string]string)
	}
	return WorkspaceRunFilterData{
		RunKey:        runKey,
		DisplayName:   msg.DisplayName,
		ID:            msg.ID,
		Project:       msg.Project,
		Notes:         strings.TrimSpace(msg.Notes),
		Tags:          normalizeRunFilterTags(msg.Tags),
		ConfigByPath:  configByPath,
		ConfigEntries: configEntries,
	}
}

func normalizeRunFilterTags(tags []string) []string {
	if len(tags) == 0 {
		return nil
	}

	out := make([]string, 0, len(tags))
	for _, tag := range tags {
		tag = strings.TrimSpace(tag)
		if tag == "" {
			continue
		}
		out = append(out, tag)
	}

	if len(out) == 0 {
		return nil
	}
	return out
}

// flattenRunFilterConfig flattens a ConfigRecord into canonicalized path/value
// pairs plus a sorted entry list for broad config searches.
func flattenRunFilterConfig(cfg *spb.ConfigRecord) (map[string]string, []RunFilterConfigEntry) {
	if cfg == nil {
		return nil, nil
	}

	flat := make(map[string]string)
	for _, item := range cfg.GetUpdate() {
		if item == nil {
			continue
		}

		path := strings.Join(item.GetNestedKey(), ".")
		if path == "" {
			path = item.GetKey()
		}
		path = strings.TrimSpace(path)
		if path == "" {
			continue
		}

		raw := strings.TrimSpace(item.GetValueJson())
		if raw == "" {
			flat[canonicalRunFilterPath(path)] = ""
			continue
		}

		var value any
		if err := json.Unmarshal([]byte(raw), &value); err != nil {
			value = trimRunFilterRawJSONValue(raw)
		}
		flattenRunFilterValue(path, value, flat)
	}

	keys := make([]string, 0, len(flat))
	for path := range flat {
		keys = append(keys, path)
	}
	sort.Strings(keys)

	entries := make([]RunFilterConfigEntry, 0, len(keys))
	for _, path := range keys {
		entries = append(entries, RunFilterConfigEntry{
			Path:  path,
			Value: flat[path],
		})
	}

	return flat, entries
}

// flattenRunFilterValue recursively expands JSON-like config values into
// canonical path/value pairs.
func flattenRunFilterValue(prefix string, value any, out map[string]string) {
	switch v := value.(type) {
	case map[string]any:
		keys := make([]string, 0, len(v))
		for key := range v {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		for _, key := range keys {
			flattenRunFilterValue(prefix+"."+key, v[key], out)
		}
	case []any:
		for i, elem := range v {
			flattenRunFilterValue(fmt.Sprintf("%s[%d]", prefix, i), elem, out)
		}
	case nil:
		out[canonicalRunFilterPath(prefix)] = "null"
	default:
		out[canonicalRunFilterPath(prefix)] = fmt.Sprint(v)
	}
}

// trimRunFilterRawJSONValue removes surrounding JSON string quotes from a raw
// config value when structured decoding is unavailable.
func trimRunFilterRawJSONValue(raw string) string {
	raw = strings.TrimSpace(raw)
	if len(raw) >= 2 && raw[0] == '"' && raw[len(raw)-1] == '"' {
		return raw[1 : len(raw)-1]
	}
	return raw
}
