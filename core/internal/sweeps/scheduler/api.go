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
type SweepAPI struct {
	gqlClient graphql.Client
	features  *featurechecker.FeatureProvider

	entity  string
	project string
	sweepID string
}

func NewSweepAPI(
	gqlClient graphql.Client,
	features *featurechecker.FeatureProvider,
	entity string,
	project string,
	sweepID string,
) *SweepAPI {
	return &SweepAPI{
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
func (a *SweepAPI) CheckLocalSchedulerSupported(ctx context.Context) error {
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
//
// Returns ErrSweepNotFound if the sweep (or its project) does not exist.
func (a *SweepAPI) FetchSweep(ctx context.Context) (*SweepFacts, error) {
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
// sweep's state.
func (a *SweepAPI) WarmStartPage(
	ctx context.Context,
	pageSize int,
	cursor *string,
	metricKeys []string,
) (*PollPage, error) {
	specs := historySpecs(metricKeys)
	data, err := gql.SweepRunsWithHistory(
		ctx, a.gqlClient,
		a.entity, a.project, a.sweepID,
		pageSize, cursor, specs,
	)
	if err != nil {
		return nil, err
	}

	state, runs, err := warmStartPollResult(data)
	if err != nil {
		return nil, err
	}
	return buildPollPage(state, runs), nil
}

// FetchWatchedRuns fetches one page of the named runs, with the sweep's
// state. Names absent from the result do not exist in the project.
func (a *SweepAPI) FetchWatchedRuns(
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

	state, runs, err := watchedRunsPollResult(data)
	if err != nil {
		return nil, err
	}
	return buildPollPage(state, runs), nil
}

// pollRuns is the run page shape shared by SweepRunsWithHistory and
// SweepWatchedRuns, via the SweepPollRuns GraphQL fragment.
type pollRuns interface {
	GetPageInfo() gql.SweepPollRunsPageInfo
	GetEdges() []gql.SweepPollRunsEdgesRunEdge
}

// warmStartPollResult extracts the sweep state and run page from a
// SweepRunsWithHistory response, which nests the run connection under
// the sweep itself.
func warmStartPollResult(
	data *gql.SweepRunsWithHistoryResponse,
) (state string, runs pollRuns, err error) {
	project := data.GetProject()
	if project == nil || project.GetSweep() == nil {
		return "", nil, ErrSweepNotFound
	}
	sweep := project.GetSweep()
	sweepRuns := sweep.GetRuns()
	return sweep.GetState(), &sweepRuns, nil
}

// watchedRunsPollResult extracts the sweep state and run page from a
// SweepWatchedRuns response, which selects the run connection as a
// sibling of the sweep, independently filtered by name.
func watchedRunsPollResult(
	data *gql.SweepWatchedRunsResponse,
) (state string, runs pollRuns, err error) {
	project := data.GetProject()
	if project == nil || project.GetSweep() == nil {
		return "", nil, ErrSweepNotFound
	}
	if projectRuns := project.GetRuns(); projectRuns != nil {
		runs = projectRuns
	}
	return project.GetSweep().GetState(), runs, nil
}

func buildPollPage(sweepState string, runs pollRuns) *PollPage {
	page := &PollPage{SweepState: sweepState}
	if runs == nil {
		return page
	}
	for _, edge := range runs.GetEdges() {
		page.Runs = append(page.Runs, pollRunFrom(edge.GetNode()))
	}
	pageInfo := runs.GetPageInfo()
	if pageInfo.GetHasNextPage() {
		page.NextCursor = pageInfo.GetEndCursor()
	}
	return page
}

func pollRunFrom(node gql.SweepPollRunsEdgesRunEdgeNodeRun) PollRun {
	return PollRun{
		StorageID:   node.Id,
		Name:        node.Name,
		State:       nullify.ZeroIfNil(node.State),
		ConfigJSON:  nullify.ZeroIfNil(node.Config),
		SummaryJSON: nullify.ZeroIfNil(node.SummaryMetrics),
		HistoryJSON: historyJSON(node.SampledHistory),
	}
}

// historySpecs builds the sampledHistory spec supporting MOO
func historySpecs(metricKeys []string) []string {
	spec, _ := json.Marshal(map[string]any{
		"keys":    append(metricKeys, stepKey),
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
func (a *SweepAPI) ConfirmRunExists(
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
func (a *SweepAPI) EnqueueRun(
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
func (a *SweepAPI) StopRun(ctx context.Context, storageID string) (bool, error) {
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
func (a *SweepAPI) UpsertSweepState(
	ctx context.Context,
	sweepNodeID string,
	state string,
) error {
	_, err := gql.UpsertSweepState(ctx, a.gqlClient, sweepNodeID, state)
	return err
}
