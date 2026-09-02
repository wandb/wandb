package wbapi

import (
	"context"
	"fmt"
	"strings"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/nullify"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// RunHandler handles run-level API requests that resolve to typed GraphQL
// operations executed by wandb-core.
type RunHandler struct {
	graphqlClient graphql.Client
}

func NewRunHandler(graphqlClient graphql.Client) *RunHandler {
	return &RunHandler{graphqlClient: graphqlClient}
}

// HandleStopRun flags a run to stop on the W&B backend.
//
// This is the same signal sent by the "Stop run" button in the W&B UI: the
// backend sets the run's stopped flag, which the process running the run
// polls during its heartbeat to shut the run down gracefully.
func (h *RunHandler) HandleStopRun(
	ctx context.Context,
	request *spb.StopRunRequest,
) *spb.ApiResponse {
	_, err := gql.StopRun(ctx, h.graphqlClient, request.GetStorageId())
	if err != nil {
		message, status := graphqlErrorInfo(err)
		return apiErrorResponse(message, status)
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_StopRunResponse{
			StopRunResponse: &spb.StopRunResponse{},
		},
	}
}

// HandleReadRunConsoleLogs reads one page of a run's captured console output.
//
// A tail request (last) uses a logLines query that behaves identically on
// every supported server. A forward-pagination request (first/after) requires
// the server's spec-compliant logLines pagination (server 0.77+): the legacy
// resolver ignores `first` and repurposes `after` as a backwards offset, so
// on older servers this returns an error instead of wrong lines.
func (h *RunHandler) HandleReadRunConsoleLogs(
	ctx context.Context,
	request *spb.ReadRunConsoleLogsRequest,
) *spb.ApiResponse {
	if request.Last != nil {
		if request.First != nil || request.After != nil {
			return apiErrorResponse(
				"cannot combine 'last' with 'first' or 'after'", 0)
		}
		if request.GetLast() <= 0 {
			return apiErrorResponse("'last' must be positive", 0)
		}
		return h.readRunConsoleLogTail(ctx, request)
	}

	if request.First != nil && request.GetFirst() <= 0 {
		return apiErrorResponse("'first' must be positive", 0)
	}
	return h.readRunConsoleLogPage(ctx, request)
}

// readRunConsoleLogTail reads the last `last` lines of the console log.
func (h *RunHandler) readRunConsoleLogTail(
	ctx context.Context,
	request *spb.ReadRunConsoleLogsRequest,
) *spb.ApiResponse {
	data, err := gql.RunConsoleLogTail(
		ctx,
		h.graphqlClient,
		request.GetEntity(),
		request.GetProject(),
		request.GetRunId(),
		int(request.GetLast()),
	)
	if err != nil {
		message, status := graphqlErrorInfo(err)
		return apiErrorResponse(message, status)
	}

	// The project is null when it does not exist or the credentials
	// cannot read it; the run is null when the run does not exist.
	project := data.GetProject()
	if project == nil || project.GetRun() == nil {
		return apiErrorResponse(runNotFoundMessage(request), 0)
	}
	run := project.GetRun()

	response := &spb.ReadRunConsoleLogsResponse{
		TotalLines: int64(nullify.ZeroIfNil(run.GetLogLineCount())),
	}
	// The connection is null for a run that never wrote console output.
	//
	// The edge cursors are intentionally not returned: a tail response's
	// cursors come from the backend's legacy pagination and cannot seed a
	// forward-pagination (`after`) request.
	if conn := run.GetLogLines(); conn != nil {
		for i := range conn.Edges {
			response.Lines = append(
				response.Lines, consoleLogLineFromNode(&conn.Edges[i].Node))
		}
	}
	return readRunConsoleLogsResponse(response)
}

// readRunConsoleLogPage reads up to `first` lines in ascending line order,
// resuming after the `after` cursor if given.
func (h *RunHandler) readRunConsoleLogPage(
	ctx context.Context,
	request *spb.ReadRunConsoleLogsRequest,
) *spb.ApiResponse {
	var first *int
	if request.First != nil {
		firstValue := int(request.GetFirst())
		first = &firstValue
	}

	data, err := gql.RunConsoleLogPage(
		ctx,
		h.graphqlClient,
		request.GetEntity(),
		request.GetProject(),
		request.GetRunId(),
		first,
		request.After, //nolint:protogetter // nil means "from the start"
	)
	if err != nil {
		message, status := graphqlErrorInfo(err)
		// The useImprovedPagination argument exists on server 0.77+;
		// older servers reject the query document during validation.
		if strings.Contains(message, "useImprovedPagination") {
			message = fmt.Sprintf(
				"reading a run's console log from the beginning requires"+
					" W&B server 0.77 or newer; request the last N lines"+
					" of the log instead (%s)",
				message,
			)
		}
		return apiErrorResponse(message, status)
	}

	// The project is null when it does not exist or the credentials
	// cannot read it; the run is null when the run does not exist.
	project := data.GetProject()
	if project == nil || project.GetRun() == nil {
		return apiErrorResponse(runNotFoundMessage(request), 0)
	}
	run := project.GetRun()

	response := &spb.ReadRunConsoleLogsResponse{
		TotalLines: int64(nullify.ZeroIfNil(run.GetLogLineCount())),
	}
	// The connection is null for a run that never wrote console output.
	if conn := run.GetLogLines(); conn != nil {
		response.EndCursor = nullify.ZeroIfNil(conn.PageInfo.GetEndCursor())
		for i := range conn.Edges {
			response.Lines = append(
				response.Lines, consoleLogLineFromNode(&conn.Edges[i].Node))
		}
		response.HasNextPage = pageHasNextLines(conn, response.TotalLines)
	}
	return readRunConsoleLogsResponse(response)
}

// pageHasNextLines reports whether the log has lines after this page.
//
// The backend can cut a page short on a per-request size budget and
// report hasNextPage=false in the middle of the log. Line numbers are
// absolute positions, so more lines exist whenever the page's last line
// is not the log's last line; this makes has_next_page trustworthy for
// every client of the proto API without any client-side bookkeeping.
// When the log's line count is unavailable (0), only the backend's flag
// is used.
func pageHasNextLines(
	conn *gql.RunConsoleLogPageProjectRunLogLinesLogLineConnection,
	totalLines int64,
) bool {
	// A page without a resume cursor cannot be continued; report it as
	// final so clients stop instead of re-reading the log from the
	// beginning.
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

// logLineNode is implemented by the generated node types of the
// RunConsoleLogTail and RunConsoleLogPage queries.
type logLineNode interface {
	GetNumber() *int
	GetTimestamp() *string
	GetLevel() *string
	GetLabel() *string
	GetLine() *string
}

func consoleLogLineFromNode(node logLineNode) *spb.RunConsoleLogLine {
	return &spb.RunConsoleLogLine{
		Number:    int64(nullify.ZeroIfNil(node.GetNumber())),
		Timestamp: nullify.ZeroIfNil(node.GetTimestamp()),
		Level:     nullify.ZeroIfNil(node.GetLevel()),
		Label:     nullify.ZeroIfNil(node.GetLabel()),
		Content:   nullify.ZeroIfNil(node.GetLine()),
	}
}

func runNotFoundMessage(request *spb.ReadRunConsoleLogsRequest) string {
	return fmt.Sprintf(
		"run %s/%s/%s not found",
		request.GetEntity(),
		request.GetProject(),
		request.GetRunId(),
	)
}

func readRunConsoleLogsResponse(
	response *spb.ReadRunConsoleLogsResponse,
) *spb.ApiResponse {
	return &spb.ApiResponse{
		Response: &spb.ApiResponse_ReadRunConsoleLogsResponse{
			ReadRunConsoleLogsResponse: response,
		},
	}
}
