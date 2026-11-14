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

// CaseService contains methods and other services that help with interacting with
// the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewCaseService] method instead.
type CaseService struct {
	Options []option.RequestOption
}

// NewCaseService generates a new service that applies the given options to each
// request. These options are applied after the parent client's options (if there
// is one), and before any request-specific options.
func NewCaseService(opts ...option.RequestOption) (r *CaseService) {
	r = &CaseService{}
	r.Options = opts
	return
}

// Returns one published case, including its input, output, variant, attributes,
// and the commit that published it.
func (r *CaseService) Get(
	ctx context.Context,
	caseID string,
	query CaseGetParams,
	opts ...option.RequestOption,
) (res *CaseGetResponse, err error) {
	opts = slices.Concat(r.Options, opts)
	precfg, err := requestconfig.PreRequestOptions(opts...)
	if err != nil {
		return nil, err
	}
	requestconfig.UseDefaultParam(&query.Namespace, precfg.Namespace)
	requestconfig.UseDefaultParam(&query.ScopeID, precfg.ScopeID)
	if query.Namespace.Value == "" {
		err = errors.New("missing required namespace parameter")
		return nil, err
	}
	if query.ScopeID.Value == "" {
		err = errors.New("missing required scope_id parameter")
		return nil, err
	}
	if caseID == "" {
		err = errors.New("missing required case_id parameter")
		return nil, err
	}
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/cases/%s", query.Namespace, query.ScopeID, caseID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, nil, &res, opts...)
	return res, err
}

type CaseGetResponse struct {
	Attributes map[string]interface{} `json:"attributes"  api:"required"`
	CaseID     string                 `json:"case_id"     api:"required"          format:"uuid"`
	CommitID   int64                  `json:"commit_id"   api:"required"`
	ExampleKey string                 `json:"example_key" api:"required,nullable"`
	Input      interface{}            `json:"input"       api:"required"`
	// Namespace that assigned the scope reference.
	Namespace CaseGetResponseNamespace `json:"namespace" api:"required"`
	Output    interface{}              `json:"output"    api:"required"`
	ScopeRef  string                   `json:"scope_ref" api:"required"`
	Variant   string                   `json:"variant"   api:"required,nullable"`
	JSON      caseGetResponseJSON      `json:"-"`
}

// caseGetResponseJSON contains the JSON metadata for the struct [CaseGetResponse]
type caseGetResponseJSON struct {
	Attributes  apijson.Field
	CaseID      apijson.Field
	CommitID    apijson.Field
	ExampleKey  apijson.Field
	Input       apijson.Field
	Namespace   apijson.Field
	Output      apijson.Field
	ScopeRef    apijson.Field
	Variant     apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *CaseGetResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r caseGetResponseJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type CaseGetResponseNamespace string

const (
	CaseGetResponseNamespaceWandb CaseGetResponseNamespace = "wandb"
)

func (r CaseGetResponseNamespace) IsKnown() bool {
	switch r {
	case CaseGetResponseNamespaceWandb:
		return true
	}
	return false
}

type CaseGetParams struct {
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
}
