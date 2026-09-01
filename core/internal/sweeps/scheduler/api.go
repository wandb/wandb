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

// PollPage fetches one page of the sweep's runs with the sweep's state.
//
// metricKey selects the metric whose sampled history each run carries;
// pass "" to skip history. Returns ErrSweepNotFound if the sweep (or
// its project) does not exist.
func (a *SweepAPI) PollPage(
	ctx context.Context,
	pageSize int,
	cursor *string,
	metricKey string,
) (*PollPage, error) {
	var specs []string
	if metricKey != "" {
		spec, err := json.Marshal(map[string]any{
			"keys":    []string{metricKey},
			"samples": historySampleCount,
		})
		if err != nil {
			return nil, fmt.Errorf("scheduler: building history spec: %v", err)
		}
		specs = []string{string(spec)}
	}

	data, err := gql.SweepRunsWithHistory(
		ctx, a.gqlClient,
		a.entity, a.project, a.sweepID,
		pageSize, cursor, specs,
	)
	if err != nil {
		return nil, err
	}

	project := data.GetProject()
	if project == nil || project.GetSweep() == nil {
		return nil, ErrSweepNotFound
	}
	sweep := project.GetSweep()

	page := &PollPage{SweepState: sweep.GetState()}
	runs := sweep.GetRuns()
	for _, edge := range runs.GetEdges() {
		node := edge.GetNode()
		page.Runs = append(page.Runs, PollRun{
			StorageID:   node.GetId(),
			Name:        node.GetName(),
			State:       nullify.ZeroIfNil(node.GetState()),
			ConfigJSON:  nullify.ZeroIfNil(node.GetConfig()),
			SummaryJSON: nullify.ZeroIfNil(node.GetSummaryMetrics()),
			HistoryJSON: historyJSON(node.GetSampledHistory()),
		})
	}
	pageInfo := runs.GetPageInfo()
	if pageInfo.GetHasNextPage() {
		page.NextCursor = pageInfo.GetEndCursor()
	}
	return page, nil
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

// ConfirmRunExists reports whether the named run still exists: a run
// can be missing from a paginated poll without being gone.
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
