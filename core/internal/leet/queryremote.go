package leet

import (
	"cmp"
	"context"
	"fmt"
	"io"
	"maps"
	"math"
	"regexp"
	"strings"
	"time"

	"github.com/charmbracelet/x/ansi"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runconfig"
	"github.com/wandb/wandb/core/internal/wbapi"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ErrRemoteNotAvailable is the error of a query that does not read W&B
// URLs yet.
var ErrRemoteNotAvailable = &QueryError{
	Code:    "not_available",
	Message: "remote runs come in the next release",
}

// ListRemoteRuns writes the runs of the W&B project params names, newest
// first, as the leet.runs/1 object of ListRuns read from the W&B server.
func ListRemoteRuns(params *RemoteRunParams, q RunsQuery, w io.Writer) error {
	clients, err := newRemoteClients(params.BaseURL, observability.NewNoOpLogger())
	if err != nil {
		return err
	}
	return listRemoteRuns(clients, params, q, w)
}

// QueryRemoteSummary writes the leet.summary/1 object of QuerySummary for
// the W&B run params names, read from the W&B server.
func QueryRemoteSummary(params *RemoteRunParams, q SummaryQuery, w io.Writer) error {
	clients, err := newRemoteClients(params.BaseURL, observability.NewNoOpLogger())
	if err != nil {
		return err
	}
	return queryRemoteSummary(clients, params, q, w)
}

// QueryRemoteConsole writes the leet.console/1 object of QueryConsole for
// the W&B run params names, read from the W&B server.
func QueryRemoteConsole(params *RemoteRunParams, q ConsoleQuery, w io.Writer) error {
	clients, err := newRemoteClients(params.BaseURL, observability.NewNoOpLogger())
	if err != nil {
		return err
	}
	return queryRemoteConsole(clients, params, q, w)
}

func remoteContext() (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.Background(), 60*time.Second)
}

// remoteURL returns the canonical URL of the project, or of the run when
// runID is set.
func (p *RemoteRunParams) remoteURL(runID string) string {
	url := p.BaseURL + "/" + p.Entity + "/" + p.Project
	if runID != "" {
		url += "/runs/" + runID
	}
	return url
}

// remoteSource returns the source field of a query object for a remote
// project, or run when runID is set.
func (p *RemoteRunParams) remoteSource(runID string) map[string]any {
	return map[string]any{
		"kind":    "remote",
		"path":    nil,
		"url":     p.remoteURL(runID),
		"entity":  p.Entity,
		"project": p.Project,
		"run_id":  orNil(runID),
	}
}

func listRemoteRuns(c *remoteClients, params *RemoteRunParams, q RunsQuery, w io.Writer) error {
	switch {
	case params.RunID != "":
		return badRequest("a project URL is required")
	case q.Limit < 0:
		return badRequest("limit must be >= 0")
	case len(q.SummaryKeys) > 0:
		return &QueryError{
			Code: "not_available",
			Message: "summary keys are not listed for remote projects yet;" +
				" read the run's summary instead",
		}
	}
	limit := cmp.Or(q.Limit, defaultRunsLimit)
	mode := FilterModeRegex
	if q.Glob {
		mode = FilterModeGlob
	}
	query := CompileRunFilterQuery(q.Filter, mode)
	logger := observability.NewNoOpLogger()

	var infos []*RunInfo
	seen := make(map[string]bool)
	var cursor *string
	more := false
	for {
		ctx, cancel := remoteContext()
		first, order := remoteRunsPageSize, "-created_at"
		response, err := gql.QueryProjectRuns(
			ctx, c.graphql, params.Entity, params.Project, &first, &order, cursor)
		cancel()
		if err != nil {
			return err
		}
		if response.Project == nil || response.Project.Runs == nil {
			return &QueryError{
				Code: "run_not_found",
				Message: fmt.Sprintf("project %s/%s not found or not readable with the"+
					" configured API key", params.Entity, params.Project),
			}
		}
		page := response.Project.Runs
		for i := range page.Edges {
			info := newRunInfo(params.Entity, params.Project, &page.Edges[i].Node.LeetRun, logger)
			if seen[info.runId] {
				continue
			}
			seen[info.runId] = true
			if query.Match(buildWorkspaceRunFilterData(info.runId, info.runMsg())) {
				infos = append(infos, info)
			}
		}
		cursor = page.PageInfo.EndCursor
		if !page.PageInfo.HasNextPage || cursor == nil || *cursor == "" {
			break
		}
		if len(infos) >= limit {
			more = true
			break
		}
	}

	runs := make([]any, 0, min(limit, len(infos)))
	for _, info := range infos[:min(limit, len(infos))] {
		runs = append(runs, info.listingJSON())
	}
	warnings := []string{}
	if more {
		warnings = append(warnings, "more runs may exist")
	}
	return encodeJSON(w, map[string]any{
		"schema":    "leet.runs/1",
		"source":    params.remoteSource(""),
		"runs":      runs,
		"total":     len(infos),
		"truncated": more || len(infos) > len(runs),
		"warnings":  warnings,
	}, "")
}

// listingJSON returns the run in the run shape of leet.runs/1.
func (ri *RunInfo) listingJSON() map[string]any {
	return map[string]any{
		"run_key":      nil,
		"run_id":       ri.runId,
		"name":         cmp.Or(ri.displayName, ri.runId),
		"entity":       ri.entity,
		"project":      ri.project,
		"state":        strings.ToLower(ri.runState.String()),
		"state_detail": ri.state,
		"start_time":   rfc3339OrNil(ri.createdAt),
		"last_write":   rfc3339OrNil(ri.heartbeatAt),
		"exit_code":    nil,
		"step":         nil,
		"tags":         append([]string{}, ri.tags...),
		"notes":        orNil(ri.notes),
		"file":         nil,
		"selected":     false,
		"pinned":       false,
	}
}

// runInfo loads the run params names from the W&B server.
func (c *remoteClients) runInfo(params *RemoteRunParams) (*RunInfo, error) {
	if params.RunID == "" {
		return nil, badRequest("a run URL is required")
	}
	ctx, cancel := remoteContext()
	defer cancel()
	return loadRunInfo(ctx, c.graphql, params.Entity, params.Project, params.RunID,
		observability.NewNoOpLogger())
}

func queryRemoteSummary(
	c *remoteClients,
	params *RemoteRunParams,
	q SummaryQuery,
	w io.Writer,
) error {
	info, err := c.runInfo(params)
	if err != nil {
		return err
	}
	req := &spb.ReadRunConsoleLogsRequest{
		Entity:  params.Entity,
		Project: params.Project,
		RunId:   params.RunID,
		Last:    proto.Int32(summaryQueryConsoleLines),
	}
	logs, err := c.consoleLogs(req)
	if err != nil {
		return err
	}

	config := map[string]any{}
	if info.config != nil {
		rc := runconfig.New()
		rc.ApplyChangeRecord(info.config, func(error) {})
		config = rc.CloneTree()
	}
	delete(config, "_wandb")
	summary := info.runSummary
	if summary == nil {
		summary = map[string]any{}
	}
	maps.DeleteFunc(summary, func(k string, _ any) bool {
		return k == "_wandb" || strings.HasPrefix(k, "_wandb.")
	})
	selected, unmatched := keySelector(q.Keys)
	out := map[string]any{
		"schema":        "leet.summary/1",
		"source":        params.remoteSource(params.RunID),
		"file":          nil,
		"run_id":        info.runId,
		"name":          cmp.Or(info.displayName, info.runId),
		"entity":        info.entity,
		"project":       info.project,
		"notes":         info.notes,
		"tags":          append([]string{}, info.tags...),
		"state":         strings.ToLower(info.runState.String()),
		"state_detail":  info.state,
		"start_time":    rfc3339OrNil(info.createdAt),
		"last_write":    rfc3339OrNil(info.heartbeatAt),
		"exit_code":     nil,
		"step":          nil,
		"summary":       selectTree(summary, "", selected),
		"config":        config,
		"history_keys":  nil,
		"console":       remoteConsoleLines(logs.GetLines(), nil, time.Time{}),
		"console_lines": logs.GetTotalLines(),
		"warnings": append([]string{"history keys are not available for remote runs"},
			unmatched()...),
		"truncated":   false,
		"has_more":    false,
		"next_cursor": nil,
	}
	if step := maxStepFromSummary(info.runSummary); step >= 0 {
		out["step"] = step
	}
	return encodeJSON(w, out, "")
}

// remoteConsoleCursor is where a page of remote console lines ended, for
// the call that continues after it: the server's cursor of its last line,
// or the cursor the call started from when the page was empty. A tail
// (last) has no server cursor, so next_cursor is null; page with limit to
// get one.
type remoteConsoleCursor struct {
	Version int    `json:"v"`
	Cursor  string `json:"c"`
	RunID   string `json:"f"`
}

func queryRemoteConsole(
	c *remoteClients,
	params *RemoteRunParams,
	q ConsoleQuery,
	w io.Writer,
) error {
	switch {
	case q.Follow:
		return &QueryError{
			Code: "not_available",
			Message: "follow is not available for remote runs;" +
				" call again with --after <next_cursor>",
		}
	case q.Last < 0, q.Limit < 0:
		return badRequest("last and limit must be >= 0")
	case q.Last > math.MaxInt32, q.Limit > math.MaxInt32:
		return badRequest("last and limit must be <= %d", math.MaxInt32)
	}
	var grep *regexp.Regexp
	var err error
	if q.Grep != "" {
		if grep, err = regexp.Compile(q.Grep); err != nil {
			return badRequest("grep: %v", err)
		}
	}
	since, sinceAgo, err := parseSince(q.Since)
	if err != nil {
		return err
	}
	after, err := remoteConsoleAfter(q.After, params.RunID)
	if err != nil {
		return err
	}
	info, err := c.runInfo(params)
	if err != nil {
		return err
	}
	live := info.runState.mayBeLive()
	if sinceAgo > 0 {
		end := time.Now()
		if !live && !info.heartbeatAt.IsZero() {
			end = info.heartbeatAt
		}
		since = end.Add(-sinceAgo)
	}

	req := &spb.ReadRunConsoleLogsRequest{
		Entity:  params.Entity,
		Project: params.Project,
		RunId:   params.RunID,
		After:   after,
	}
	paged := q.After != "" || q.Limit > 0
	if paged {
		req.First = proto.Int32(int32(cmp.Or(q.Limit, defaultConsoleLimit)))
	} else {
		req.Last = proto.Int32(int32(cmp.Or(q.Last, defaultConsoleLast)))
	}
	logs, err := c.consoleLogs(req)
	if err != nil {
		return err
	}

	lines := remoteConsoleLines(logs.GetLines(), grep, since)
	out := map[string]any{
		"schema":        "leet.console/1",
		"source":        params.remoteSource(params.RunID),
		"state":         strings.ToLower(info.runState.String()),
		"exit_code":     nil,
		"run_id":        info.runId,
		"total_lines":   logs.GetTotalLines(),
		"matched_lines": len(lines),
		"lines":         lines,
		"truncated":     logs.GetHasNextPage(),
		"has_more":      paged && logs.GetHasNextPage(),
		"next_cursor":   nextRemoteConsoleCursor(logs, after, params.RunID, live),
		"warnings":      []string{},
	}
	if !paged {
		out["truncated"] = logs.GetTotalLines() > int64(len(logs.GetLines()))
		if q.Grep == "" && q.Since == "" {
			out["matched_lines"] = logs.GetTotalLines()
		} else {
			out["warnings"] = []string{fmt.Sprintf("grep and since filtered only the"+
				" last %d lines the server returned; page with limit to search the whole"+
				" log", len(logs.GetLines()))}
		}
	}
	return encodeJSON(w, out, "")
}

// remoteConsoleAfter returns the server cursor the cursor after carries,
// or nil for no cursor.
func remoteConsoleAfter(after, runID string) (*string, error) {
	if after == "" {
		return nil, nil
	}
	var cur remoteConsoleCursor
	if err := decodeCursor(after, &cur); err != nil {
		return nil, err
	}
	switch {
	case cur.Version != 1:
		return nil, badRequest("after: unsupported cursor version")
	case cur.Cursor == "":
		return nil, badRequest("after: not a cursor from a previous call")
	case cur.RunID != runID:
		return nil, badRequest("after: the cursor is from another run")
	}
	return &cur.Cursor, nil
}

// nextRemoteConsoleCursor returns the next_cursor of a page or tail: the
// server's cursor of its last line, or the cursor it started from when it
// was empty, while the log has more lines or the run may log more.
func nextRemoteConsoleCursor(
	logs *spb.ReadRunConsoleLogsResponse,
	after *string,
	runID string,
	live bool,
) any {
	cursor := logs.GetEndCursor()
	if cursor == "" && after != nil {
		cursor = *after
	}
	if cursor != "" && (logs.GetHasNextPage() || live) {
		return encodeCursor(remoteConsoleCursor{Version: 1, Cursor: cursor, RunID: runID})
	}
	return nil
}

// consoleLogs reads one tail or page of a run's console log from the W&B
// server. A server too old to page from the start is server_too_old, and
// a cursor the server rejects is bad_request.
func (c *remoteClients) consoleLogs(
	req *spb.ReadRunConsoleLogsRequest,
) (*spb.ReadRunConsoleLogsResponse, error) {
	ctx, cancel := remoteContext()
	defer cancel()
	resp := wbapi.NewRunHandler(c.graphql).HandleReadRunConsoleLogs(ctx, req)
	if e := resp.GetApiErrorResponse(); e != nil {
		code := "internal"
		switch {
		case strings.Contains(e.GetMessage(), "W&B server 0.77"):
			code = "server_too_old"
		case strings.Contains(e.GetMessage(), "invalid cursor"):
			code = "bad_request"
		}
		return nil, &QueryError{Code: code, Message: e.GetMessage()}
	}
	return resp.GetReadRunConsoleLogsResponse(), nil
}

// remoteConsoleLines returns the lines that grep and since keep, in the
// line shape of leet.console/1, numbered as the server numbers them.
func remoteConsoleLines(
	lines []*spb.RunConsoleLogLine,
	grep *regexp.Regexp,
	since time.Time,
) []any {
	out := make([]any, 0, len(lines))
	for _, line := range lines {
		at, err := time.Parse(time.RFC3339Nano, line.GetTimestamp())
		if err != nil {
			at, _ = time.Parse("2006-01-02T15:04:05.999999999", line.GetTimestamp())
		}
		content := ansi.Strip(line.GetContent())
		if grep != nil && !grep.MatchString(content) {
			continue
		}
		if !since.IsZero() && !at.IsZero() && at.Before(since) {
			continue
		}
		level := ""
		if line.GetLevel() == "error" {
			level = "error"
		}
		out = append(out, map[string]any{
			"number":    line.GetNumber(),
			"timestamp": rfc3339OrNil(at),
			"level":     level,
			"label":     line.GetLabel(),
			"content":   content,
		})
	}
	return out
}
