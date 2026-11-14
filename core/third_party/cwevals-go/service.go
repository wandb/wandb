// File generated from our OpenAPI spec by Stainless.

package cwevals

import (
	"context"
	"net/http"
	"slices"

	"github.com/wandb/cwevals-go/internal/apijson"
	"github.com/wandb/cwevals-go/internal/requestconfig"
	"github.com/wandb/cwevals-go/option"
)

// ServiceService contains methods and other services that help with interacting
// with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewServiceService] method instead.
type ServiceService struct {
	Options []option.RequestOption
}

// NewServiceService generates a new service that applies the given options to each
// request. These options are applied after the parent client's options (if there
// is one), and before any request-specific options.
func NewServiceService(opts ...option.RequestOption) (r *ServiceService) {
	r = &ServiceService{}
	r.Options = opts
	return
}

// Get
func (r *ServiceService) Get(ctx context.Context, opts ...option.RequestOption) (res *ServiceGetResponse, err error) {
	opts = slices.Concat(r.Options, opts)
	path := ""
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, nil, &res, opts...)
	return res, err
}

type ServiceGetResponse struct {
	Message string                 `json:"message" api:"required"`
	JSON    serviceGetResponseJSON `json:"-"`
}

// serviceGetResponseJSON contains the JSON metadata for the struct
// [ServiceGetResponse]
type serviceGetResponseJSON struct {
	Message     apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *ServiceGetResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r serviceGetResponseJSON) RawJSON() string {
	return r.raw
}
