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

// VerificationService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewVerificationService] method instead.
type VerificationService struct {
	Options []option.RequestOption
}

// NewVerificationService generates a new service that applies the given options to
// each request. These options are applied after the parent client's options (if
// there is one), and before any request-specific options.
func NewVerificationService(opts ...option.RequestOption) (r *VerificationService) {
	r = &VerificationService{}
	r.Options = opts
	return
}

// Get test
func (r *VerificationService) Get(
	ctx context.Context,
	opts ...option.RequestOption,
) (res *VerificationGetResponse, err error) {
	opts = slices.Concat(r.Options, opts)
	path := "test"
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, nil, &res, opts...)
	return res, err
}

type VerificationGetResponse struct {
	Message string                      `json:"message" api:"required"`
	JSON    verificationGetResponseJSON `json:"-"`
}

// verificationGetResponseJSON contains the JSON metadata for the struct
// [VerificationGetResponse]
type verificationGetResponseJSON struct {
	Message     apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *VerificationGetResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r verificationGetResponseJSON) RawJSON() string {
	return r.raw
}
