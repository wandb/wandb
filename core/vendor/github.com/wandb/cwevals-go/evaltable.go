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

// EvalTableService contains methods and other services that help with interacting
// with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewEvalTableService] method instead.
type EvalTableService struct {
	Options  []option.RequestOption
	Columns  *EvalTableColumnService
	Rows     *EvalTableRowService
	Versions *EvalTableVersionService
}

// NewEvalTableService generates a new service that applies the given options to
// each request. These options are applied after the parent client's options (if
// there is one), and before any request-specific options.
func NewEvalTableService(opts ...option.RequestOption) (r *EvalTableService) {
	r = &EvalTableService{}
	r.Options = opts
	r.Columns = NewEvalTableColumnService(opts...)
	r.Rows = NewEvalTableRowService(opts...)
	r.Versions = NewEvalTableVersionService(opts...)
	return
}

// Creates a dataset and a live evaluation together so you can log inputs, outputs,
// and scores as rows.
//
// Use the returned `evaluation_id` for this table's column, row, and version
// operations. The returned `dataset_id` identifies the underlying dataset.
//
// Request bodies must be at most 1 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *EvalTableService) New(
	ctx context.Context,
	params EvalTableNewParams,
	opts ...option.RequestOption,
) (res *EvalTableNewResponse, err error) {
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
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/eval-tables", params.Namespace, params.ScopeID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

type EvalTableNewResponse struct {
	Attributes   map[string]interface{} `json:"attributes"    api:"required"`
	DatasetID    string                 `json:"dataset_id"    api:"required" format:"uuid"`
	EvaluationID string                 `json:"evaluation_id" api:"required" format:"uuid"`
	Name         string                 `json:"name"          api:"required"`
	// Namespace that assigned the scope reference.
	Namespace EvalTableNewResponseNamespace `json:"namespace" api:"required"`
	ScopeRef  string                        `json:"scope_ref" api:"required"`
	JSON      evalTableNewResponseJSON      `json:"-"`
}

// evalTableNewResponseJSON contains the JSON metadata for the struct
// [EvalTableNewResponse]
type evalTableNewResponseJSON struct {
	Attributes   apijson.Field
	DatasetID    apijson.Field
	EvaluationID apijson.Field
	Name         apijson.Field
	Namespace    apijson.Field
	ScopeRef     apijson.Field
	raw          string
	ExtraFields  map[string]apijson.Field
}

func (r *EvalTableNewResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableNewResponseJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type EvalTableNewResponseNamespace string

const (
	EvalTableNewResponseNamespaceWandb EvalTableNewResponseNamespace = "wandb"
)

func (r EvalTableNewResponseNamespace) IsKnown() bool {
	switch r {
	case EvalTableNewResponseNamespaceWandb:
		return true
	}
	return false
}

type EvalTableNewParams struct {
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
	ScopeID    param.Field[string]                 `path:"scope_id" api:"required"`
	Name       param.Field[string]                 `                api:"required" json:"name"`
	Attributes param.Field[map[string]interface{}] `                               json:"attributes"`
	// Location of externally stored data, such as s3://bucket/prefix/ or
	// hf://datasets/org/name. The service stores this URI as metadata and does not
	// read from it. Dataset versions inherit it until you supply a replacement when
	// publishing a version.
	Uri param.Field[string] `json:"uri" format:"uri"`
}

func (r EvalTableNewParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}
