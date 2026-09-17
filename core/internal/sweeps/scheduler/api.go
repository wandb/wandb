package scheduler

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/nullify"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// SweepAPI is the scheduler's typed view of the W&B backend.
//
// Every call is scoped to the one sweep the API was opened for.
type SweepAPI interface {
	CheckLocalSchedulerSupported(ctx context.Context) error

	FetchSweep(ctx context.Context) (*SweepFacts, error)

	WarmStartPage(
		ctx context.Context,
		pageSize int,
		cursor *string,
	) (*PollPage, error)

	FetchWatchedRuns(
		ctx context.Context,
		names []string,
		pageSize int,
		cursor *string,
		metricKeys []string,
	) (*PollPage, error)

	ConfirmRunExists(ctx context.Context, runName string) (bool, error)

	EnqueueRun(
		ctx context.Context,
		sweepNodeID string,
		configWireJSON string,
	) (string, error)

	StopRun(ctx context.Context, storageID string) (bool, error)

	UpsertSweepState(
		ctx context.Context,
		sweepNodeID string,
		state string,
	) error
}

// sweepApi implements SweepAPI over the W&B GraphQL API.
type sweepApi struct {
	gqlClient graphql.Client
	features  *featurechecker.FeatureProvider

	entity  string
	project string
	sweepID string
}

var _ SweepAPI = (*sweepApi)(nil)

// NewSweepAPI opens the API for one sweep.
func NewSweepAPI(
	gqlClient graphql.Client,
	features *featurechecker.FeatureProvider,
	entity string,
	project string,
	sweepID string,
) *sweepApi {
	return &sweepApi{
		gqlClient: gqlClient,
		features:  features,
		entity:    entity,
		project:   project,
		sweepID:   sweepID,
	}
}

// SweepFacts is the sweep as fetched at init and on state checks.
type SweepFacts struct {
	NodeID      string
	State       string
	Config      string
	DisplayName string

	// ControllerRunName is the run collecting the scheduler's logs.
	ControllerRunName string
}

// PollRun is one run row from a poll page.
type PollRun struct {
	// StorageID is the run's GraphQL node id, used to stop the run.
	StorageID string
	Name      string
	State     string

	// {param: {"value": v}}, as a JSON object string.
	ConfigJSON  string
	SummaryJSON string

	// HistoryJSON is empty on a warm-start page, which does not sample
	// history.
	HistoryJSON string
}

// PollPage is one page of the sweep's runs plus the sweep's state.
type PollPage struct {
	SweepState string
	Runs       []PollRun
	NextCursor *string
}

// CheckLocalSchedulerSupported returns ErrUnsupportedServer if the W&B
// server cannot schedule runs enqueued by a local scheduler.
func (a *sweepApi) CheckLocalSchedulerSupported(ctx context.Context) error {
	enabled := a.features.Enabled(
		ctx,
		spb.ServerFeature_SWEEPS_LOCAL_SCHEDULER,
	)
	if !enabled {
		return ErrUnsupportedServer
	}
	return nil
}

// FetchSweep fetches the sweep's facts.
func (a *sweepApi) FetchSweep(ctx context.Context) (*SweepFacts, error) {
	data, err := gql.SweepConfig(
		ctx, a.gqlClient,
		a.entity, a.project, a.sweepID,
	)
	if err != nil {
		return nil, err
	}

	project := data.GetProject()
	if project == nil || project.GetSweep() == nil {
		return nil, ErrSweepNotFound
	}

	sweep := project.GetSweep()
	return &SweepFacts{
		NodeID:            sweep.GetId(),
		State:             sweep.GetState(),
		Config:            sweep.GetConfig(),
		DisplayName:       nullify.ZeroIfNil(sweep.GetDisplayName()),
		ControllerRunName: sweep.GetControllerRunName(),
	}, nil
}

// WarmStartPage fetches one page of every run in the sweep, with the
// sweep's state. The runs carry no history: a prior run is replayed
// from its final result. Returns ErrSweepNotFound if the sweep (or its
// project) does not exist.
func (a *sweepApi) WarmStartPage(
	ctx context.Context,
	pageSize int,
	cursor *string,
) (*PollPage, error) {
	data, err := gql.SweepPriorRuns(
		ctx, a.gqlClient,
		a.entity, a.project, a.sweepID,
		pageSize, cursor,
	)
	if err != nil {
		return nil, err
	}

	// The query nests the run connection under the sweep itself.
	project := data.GetProject()
	if project == nil || project.GetSweep() == nil {
		return nil, ErrSweepNotFound
	}

	sweep := project.GetSweep()
	runs := sweep.GetRuns()
	page := &PollPage{SweepState: sweep.GetState()}
	for _, edge := range runs.GetEdges() {
		node := edge.GetNode()
		page.Runs = append(page.Runs, pollRunFrom(&node))
	}
	pageInfo := runs.GetPageInfo()
	page.NextCursor = nextCursor(&pageInfo)
	return page, nil
}

// FetchWatchedRuns fetches one page of the named runs, with the sweep's
// state. Names absent from the result do not exist in the project.
// Returns ErrSweepNotFound if the sweep (or its project) does not exist.
func (a *sweepApi) FetchWatchedRuns(
	ctx context.Context,
	names []string,
	pageSize int,
	cursor *string,
	metricKeys []string,
) (*PollPage, error) {
	specs := historySpecs(metricKeys)
	filters := nameFilter(names)

	data, err := gql.SweepWatchedRuns(
		ctx, a.gqlClient,
		a.entity, a.project, a.sweepID,
		filters, pageSize, cursor, specs,
	)
	if err != nil {
		return nil, err
	}

	// The query selects the run connection as a sibling of the sweep,
	// independently filtered by name.
	project := data.GetProject()
	if project == nil || project.GetSweep() == nil {
		return nil, ErrSweepNotFound
	}

	page := &PollPage{SweepState: project.GetSweep().GetState()}
	runs := project.GetRuns()
	if runs == nil {
		return page, nil
	}

	for _, edge := range runs.GetEdges() {
		node := edge.GetNode()
		row := pollRunFrom(&node)
		row.HistoryJSON = historyJSON(node.GetSampledHistory())
		page.Runs = append(page.Runs, row)
	}
	pageInfo := runs.GetPageInfo()
	page.NextCursor = nextCursor(&pageInfo)
	return page, nil
}

// runNode is the per-run result both run queries read, via the
// SweepRunResult GraphQL fragment. Only the poll query also samples
// history, so that field is read off the node itself.
type runNode interface {
	GetId() string
	GetName() string
	GetState() *string
	GetConfig() *string
	GetSummaryMetrics() *string
}

// runPageInfo is the pagination shape both run queries read.
type runPageInfo interface {
	GetHasNextPage() bool
	GetEndCursor() *string
}

func pollRunFrom(node runNode) PollRun {
	return PollRun{
		StorageID:   node.GetId(),
		Name:        node.GetName(),
		State:       nullify.ZeroIfNil(node.GetState()),
		ConfigJSON:  nullify.ZeroIfNil(node.GetConfig()),
		SummaryJSON: nullify.ZeroIfNil(node.GetSummaryMetrics()),
	}
}

// nextCursor is the cursor to resume the walk from, or nil if the page
// just read was the last.
func nextCursor(info runPageInfo) *string {
	if !info.GetHasNextPage() {
		return nil
	}
	return info.GetEndCursor()
}

// historySpecs builds the sampledHistory spec for the given metrics.
func historySpecs(metricKeys []string) []string {
	keys := append(append([]string{}, metricKeys...), stepKey)
	spec, _ := json.Marshal(map[string]any{
		"keys":    keys,
		"samples": historySampleCount,
	})
	return []string{string(spec)}
}

// nameFilter selects exactly the named runs. It deliberately does not
// also constrain the sweep, so a run moved out of one still reads back
// rather than looking deleted.
func nameFilter(names []string) string {
	encoded, _ := json.Marshal(map[string]any{
		"name": map[string]any{"$in": names},
	})
	return string(encoded)
}

// historyJSON re-encodes the first spec's sampled rows as a JSON array.
func historyJSON(sampled []any) string {
	if len(sampled) == 0 {
		return ""
	}
	encoded, err := json.Marshal(sampled[0])
	if err != nil {
		return ""
	}
	return string(encoded)
}

// ConfirmRunExists reports whether the named run still exists. The run
// listing lags writes, so absence from it proves nothing; this read is
// strongly consistent.
func (a *sweepApi) ConfirmRunExists(
	ctx context.Context,
	runName string,
) (bool, error) {
	data, err := gql.RunState(
		ctx, a.gqlClient,
		a.entity, a.project, runName,
	)
	if err != nil {
		return false, err
	}

	project := data.GetProject()
	return project != nil && project.GetRun() != nil, nil
}

// EnqueueRun queues a run with the given wire-form config and returns
// the id the backend minted: the name of a run guaranteed to appear in
// the sweep as pending.
func (a *sweepApi) EnqueueRun(
	ctx context.Context,
	sweepNodeID string,
	configWireJSON string,
) (string, error) {
	// No display name: the run keeps whatever the backend assigns.
	data, err := gql.EnqueueSweepRun(
		ctx, a.gqlClient,
		sweepNodeID, configWireJSON, nil,
	)
	if err != nil {
		return "", err
	}

	payload := data.GetEnqueueSweepRun()
	if payload == nil {
		return "", fmt.Errorf("scheduler: enqueueSweepRun returned no payload")
	}
	return nullify.ZeroIfNil(payload.GetId()), nil
}

// StopRun asks the backend to stop the run with the given node id.
//
// Returns false when the backend refused, e.g. an already-stopped run.
func (a *sweepApi) StopRun(ctx context.Context, storageID string) (bool, error) {
	data, err := gql.StopRun(ctx, a.gqlClient, storageID)
	if err != nil {
		return false, err
	}

	payload := data.GetStopRun()
	if payload == nil {
		return false, nil
	}
	return payload.GetSuccess(), nil
}

// UpsertSweepState sets the sweep's state, e.g. "FINISHED".
func (a *sweepApi) UpsertSweepState(
	ctx context.Context,
	sweepNodeID string,
	state string,
) error {
	_, err := gql.UpsertSweepState(ctx, a.gqlClient, sweepNodeID, state)
	return err
}
