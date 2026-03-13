package leet

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	tea "charm.land/bubbletea/v2"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func (w *Workspace) handleRunFilterKey(msg tea.KeyPressMsg) {
	if w.filter.HandleKey(msg) {
		w.applyRunFilter()
	}
}

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

func (w *Workspace) handleClearRunsFilter(tea.KeyPressMsg) tea.Cmd {
	if w.filter.Query() == "" && !w.filter.IsActive() {
		return nil
	}
	w.filter.Clear()
	w.applyRunFilter()
	return nil
}

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

func (w *Workspace) applyRunFilter() {
	prevCursorKey := ""
	if cur, ok := w.runs.CurrentItem(); ok {
		prevCursorKey = cur.Key
	}

	query := w.filter.Query()
	if query == "" {
		w.runs.FilteredItems = w.runs.Items
	} else {
		compiled := compileRunFilterQuery(query, w.filter.Mode())
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

func (w *Workspace) runFilterData(runKey string) workspaceRunFilterData {
	data, ok := w.runsFilterIndex[runKey]
	if ok {
		return data
	}
	return workspaceRunFilterData{RunKey: runKey}
}

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
		if len(data.ConfigEntries) == 0 && len(existing.ConfigEntries) > 0 {
			data.ConfigByPath = existing.ConfigByPath
			data.ConfigEntries = existing.ConfigEntries
		}
	}
	w.runsFilterIndex[runKey] = data
}

func buildWorkspaceRunFilterData(runKey string, msg RunMsg) workspaceRunFilterData {
	configByPath, configEntries := flattenRunFilterConfig(msg.Config)
	if configByPath == nil {
		configByPath = make(map[string]string)
	}
	return workspaceRunFilterData{
		RunKey:        runKey,
		DisplayName:   msg.DisplayName,
		ID:            msg.ID,
		Project:       msg.Project,
		ConfigByPath:  configByPath,
		ConfigEntries: configEntries,
	}
}

func flattenRunFilterConfig(cfg *spb.ConfigRecord) (map[string]string, []runFilterConfigEntry) {
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

	entries := make([]runFilterConfigEntry, 0, len(keys))
	for _, path := range keys {
		entries = append(entries, runFilterConfigEntry{
			Path:  path,
			Value: flat[path],
		})
	}

	return flat, entries
}

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

func trimRunFilterRawJSONValue(raw string) string {
	raw = strings.TrimSpace(raw)
	if len(raw) >= 2 && raw[0] == '"' && raw[len(raw)-1] == '"' {
		return raw[1 : len(raw)-1]
	}
	return raw
}
