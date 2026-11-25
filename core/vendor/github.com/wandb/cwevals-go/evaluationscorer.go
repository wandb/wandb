// File generated from our OpenAPI spec by Stainless.

package cwevals

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"slices"

	"github.com/wandb/cwevals-go/internal/apijson"
	"github.com/wandb/cwevals-go/internal/param"
	"github.com/wandb/cwevals-go/internal/requestconfig"
	"github.com/wandb/cwevals-go/option"
)

// EvaluationScorerService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewEvaluationScorerService] method instead.
type EvaluationScorerService struct {
	Options []option.RequestOption
}

// NewEvaluationScorerService generates a new service that applies the given
// options to each request. These options are applied after the parent client's
// options (if there is one), and before any request-specific options.
func NewEvaluationScorerService(opts ...option.RequestOption) (r *EvaluationScorerService) {
	r = &EvaluationScorerService{}
	r.Options = opts
	return
}

// Atomically adds Scorers to the Evaluation's pending head or selects another
// version of an already registered Scorer. Published EvaluationVersions keep their
// selections. The Evaluation's latest data reads the selected versions' Scores.
// Saved EvaluationQueries name ScorerVersions, so create a new query when
// replacing a version used by an existing query. Every version must score cases or
// trajectories. A version that cannot score the targets of a saved query that
// groups by its scorer, or uses it as a pass_at_k task, returns 400. A missing
// Scorer or version returns 404, and a name already registered to another Scorer
// returns 409. Repeating the same selections changes nothing. If any item is
// invalid, no selections change.
//
// Request bodies must be at most 1 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *EvaluationScorerService) Add(
	ctx context.Context,
	evaluationID string,
	params EvaluationScorerAddParams,
	opts ...option.RequestOption,
) (res *EvaluationScorerAddResponse, err error) {
	opts = slices.Concat(r.Options, opts)
	precfg, err := requestconfig.PreRequestOptions(opts...)
	if err != nil {
		return nil, err
	}
	requestconfig.UseDefaultParam(&params.Namespace, precfg.Namespace)
	requestconfig.UseDefaultParam(&params.ScopeID, precfg.ScopeID)
	if params.Namespace.Value == "" {
		err = errors.New("missing required namespace parameter")
		return nil, err
	}
	if params.ScopeID.Value == "" {
		err = errors.New("missing required scope_id parameter")
		return nil, err
	}
	if evaluationID == "" {
		err = errors.New("missing required evaluation_id parameter")
		return nil, err
	}
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/evaluations/%s/scorers",
		params.Namespace,
		params.ScopeID,
		evaluationID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPatch, path, params, &res, opts...)
	return res, err
}

type EvaluationScorerAddResponse struct {
	// The ScorerVersions the next EvaluationVersion selects, in order.
	Scorers []EvaluationScorerAddResponseScorer `json:"scorers" api:"required"`
	JSON    evaluationScorerAddResponseJSON     `json:"-"`
}

// evaluationScorerAddResponseJSON contains the JSON metadata for the struct
// [EvaluationScorerAddResponse]
type evaluationScorerAddResponseJSON struct {
	Scorers     apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationScorerAddResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationScorerAddResponseJSON) RawJSON() string {
	return r.raw
}

type EvaluationScorerAddResponseScorer struct {
	ScorerID  string                                `json:"scorer_id"  api:"required" format:"uuid"`
	VersionID string                                `json:"version_id" api:"required" format:"uuid"`
	JSON      evaluationScorerAddResponseScorerJSON `json:"-"`
}

// evaluationScorerAddResponseScorerJSON contains the JSON metadata for the struct
// [EvaluationScorerAddResponseScorer]
type evaluationScorerAddResponseScorerJSON struct {
	ScorerID    apijson.Field
	VersionID   apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationScorerAddResponseScorer) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationScorerAddResponseScorerJSON) RawJSON() string {
	return r.raw
}

type EvaluationScorerAddParams struct {
	// Namespace that assigned the scope reference.
	//
	// Defaults to "wandb" if not set.
	Namespace param.Field[string] `path:"namespace" api:"required"`
	// Project reference assigned by the namespace. For wandb, use the internal W&B
	// project ID, not the project name or entity/project path.
	//
	// Percent-encode reserved characters so the reference occupies one URL path
	// segment. Only printable ASCII is accepted. References are compared exactly,
	// without parsing.
	//
	// Use [option.WithScopeID] on the client to set a global default for this field.
	ScopeID param.Field[string] `path:"scope_id" api:"required"`
	// Scorer versions to add. Each Scorer ID must be unique. An already registered
	// Scorer changes to the supplied version, which must keep its registered name and
	// value type.
	Scorers param.Field[[]EvaluationScorerAddParamsScorer] `json:"scorers" api:"required"`
}

func (r EvaluationScorerAddParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type EvaluationScorerAddParamsScorer struct {
	ScorerID  param.Field[string] `json:"scorer_id"  api:"required" format:"uuid"`
	VersionID param.Field[string] `json:"version_id" api:"required" format:"uuid"`
}

func (r EvaluationScorerAddParamsScorer) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}
