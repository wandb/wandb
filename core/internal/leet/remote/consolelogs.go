package remote

import (
	"context"
	"strings"
	"time"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/nullify"
)

const (
	consoleLogPageSize     = 1000
	consoleLogTailFallback = 10000
)

// Line is a single line from a run's captured console output on the backend.
type Line struct {
	Timestamp time.Time
	Content   string
	IsStderr  bool
}

// ConsoleLogReader pages through a run's console log on the W&B backend.
type ConsoleLogReader struct {
	client  graphql.Client
	entity  string
	project string
	runID   string

	cursor          *string
	done            bool
	useTailFallback bool
}

// NewConsoleLogReader creates a reader for a run's backend console log.
func NewConsoleLogReader(
	client graphql.Client,
	entity, project, runID string,
) *ConsoleLogReader {
	return &ConsoleLogReader{
		client:  client,
		entity:  entity,
		project: project,
		runID:   runID,
	}
}

// HasMore reports whether additional console log pages remain.
func (r *ConsoleLogReader) HasMore() bool {
	return !r.done
}

// ReadPage fetches the next page of console log lines.
func (r *ConsoleLogReader) ReadPage(ctx context.Context) ([]Line, error) {
	if r.done {
		return nil, nil
	}

	if r.useTailFallback {
		return r.readTail(ctx)
	}

	first := consoleLogPageSize
	data, err := gql.RunConsoleLogPage(
		ctx,
		r.client,
		r.entity,
		r.project,
		r.runID,
		&first,
		r.cursor,
	)
	if err != nil {
		if strings.Contains(err.Error(), "useImprovedPagination") {
			r.useTailFallback = true
			return r.readTail(ctx)
		}
		return nil, err
	}

	project := data.GetProject()
	if project == nil || project.GetRun() == nil {
		r.done = true
		return nil, nil
	}
	run := project.GetRun()

	conn := run.GetLogLines()
	if conn == nil || len(conn.Edges) == 0 {
		r.done = true
		return nil, nil
	}

	lines := linesFromPageEdges(conn.Edges)
	totalLines := int64(nullify.ZeroIfNil(run.GetLogLineCount()))
	r.cursor = conn.PageInfo.GetEndCursor()
	if !consoleLogPageHasNext(conn, totalLines) {
		r.done = true
	}
	return lines, nil
}

func (r *ConsoleLogReader) readTail(ctx context.Context) ([]Line, error) {
	data, err := gql.RunConsoleLogTail(
		ctx,
		r.client,
		r.entity,
		r.project,
		r.runID,
		consoleLogTailFallback,
	)
	if err != nil {
		return nil, err
	}

	project := data.GetProject()
	if project == nil || project.GetRun() == nil {
		r.done = true
		return nil, nil
	}

	conn := project.GetRun().GetLogLines()
	var lines []Line
	if conn != nil {
		lines = linesFromTailEdges(conn.Edges)
	}
	r.done = true
	return lines, nil
}

func linesFromPageEdges(
	edges []gql.RunConsoleLogPageProjectRunLogLinesLogLineConnectionEdgesLogLineEdge,
) []Line {
	lines := make([]Line, 0, len(edges))
	for i := range edges {
		lines = append(lines, lineFromNode(&edges[i].Node))
	}
	return lines
}

func linesFromTailEdges(
	edges []gql.RunConsoleLogTailProjectRunLogLinesLogLineConnectionEdgesLogLineEdge,
) []Line {
	lines := make([]Line, 0, len(edges))
	for i := range edges {
		lines = append(lines, lineFromNode(&edges[i].Node))
	}
	return lines
}

type logLineNode interface {
	GetTimestamp() *string
	GetLevel() *string
	GetLine() *string
}

func lineFromNode(node logLineNode) Line {
	content := nullify.ZeroIfNil(node.GetLine())
	level := nullify.ZeroIfNil(node.GetLevel())
	return Line{
		Timestamp: parseConsoleLogTimestamp(
			nullify.ZeroIfNil(node.GetTimestamp()),
		),
		Content:  content,
		IsStderr: level == "error",
	}
}

// consoleLogPageHasNext mirrors wbapi.pageHasNextLines for the page query.
func consoleLogPageHasNext(
	conn *gql.RunConsoleLogPageProjectRunLogLinesLogLineConnection,
	totalLines int64,
) bool {
	if nullify.ZeroIfNil(conn.PageInfo.GetEndCursor()) == "" {
		return false
	}
	if conn.PageInfo.GetHasNextPage() {
		return true
	}
	if len(conn.Edges) == 0 {
		return false
	}
	lastNumber := nullify.ZeroIfNil(conn.Edges[len(conn.Edges)-1].Node.GetNumber())
	return int64(lastNumber)+1 < totalLines
}

func parseConsoleLogTimestamp(value string) time.Time {
	if value == "" {
		return time.Time{}
	}
	parsed, err := time.Parse(time.RFC3339Nano, value)
	if err != nil {
		return time.Time{}
	}
	return parsed.UTC()
}
