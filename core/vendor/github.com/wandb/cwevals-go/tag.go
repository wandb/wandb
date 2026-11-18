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

// TagService contains methods and other services that help with interacting with
// the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewTagService] method instead.
type TagService struct {
	Options []option.RequestOption
}

// NewTagService generates a new service that applies the given options to each
// request. These options are applied after the parent client's options (if there
// is one), and before any request-specific options.
func NewTagService(opts ...option.RequestOption) (r *TagService) {
	r = &TagService{}
	r.Options = opts
	return
}

// Returns every tag name in the scope, sorted by name.
func (r *TagService) List(
	ctx context.Context,
	query TagListParams,
	opts ...option.RequestOption,
) (res *TagListResponse, err error) {
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
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/tags", query.Namespace, query.ScopeID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, nil, &res, opts...)
	return res, err
}

type TagListResponse struct {
	Tags []TagListResponseTag `json:"tags" api:"required"`
	JSON tagListResponseJSON  `json:"-"`
}

// tagListResponseJSON contains the JSON metadata for the struct [TagListResponse]
type tagListResponseJSON struct {
	Tags        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *TagListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r tagListResponseJSON) RawJSON() string {
	return r.raw
}

type TagListResponseTag struct {
	Name string                 `json:"name" api:"required"`
	JSON tagListResponseTagJSON `json:"-"`
}

// tagListResponseTagJSON contains the JSON metadata for the struct
// [TagListResponseTag]
type tagListResponseTagJSON struct {
	Name        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *TagListResponseTag) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r tagListResponseTagJSON) RawJSON() string {
	return r.raw
}

type TagListParams struct {
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
