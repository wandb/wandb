// Copyright 2018 The Go Cloud Development Kit Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// Package aws provides fundamental Wire providers for Amazon Web Services (AWS).
package aws // import "gocloud.dev/aws"

import (
	"context"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/aws/ratelimit"
	"github.com/aws/aws-sdk-go-v2/aws/retry"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials/stscreds"
	"github.com/aws/aws-sdk-go-v2/service/sts"
)

const (
	requestChecksumCalculationParamKey = "request_checksum_calculation"
	responseChecksumValidationParamKey = "response_checksum_validation"
)

// parseRequestChecksumCalculation parses request checksum calculation mode values.
// Supports AWS SDK documented values: "when_supported", "when_required".
func parseRequestChecksumCalculation(value string) (aws.RequestChecksumCalculation, error) {
	switch strings.ToLower(value) {
	case "when_supported":
		return aws.RequestChecksumCalculationWhenSupported, nil
	case "when_required":
		return aws.RequestChecksumCalculationWhenRequired, nil
	default:
		return aws.RequestChecksumCalculationWhenSupported, fmt.Errorf("invalid value for %q: %q. Valid values are: when_supported, when_required", requestChecksumCalculationParamKey, value)
	}
}

// parseResponseChecksumValidation parses response checksum validation mode values.
// Supports AWS SDK documented values: "when_supported", "when_required".
func parseResponseChecksumValidation(value string) (aws.ResponseChecksumValidation, error) {
	switch strings.ToLower(value) {
	case "when_supported":
		return aws.ResponseChecksumValidationWhenSupported, nil
	case "when_required":
		return aws.ResponseChecksumValidationWhenRequired, nil
	default:
		return aws.ResponseChecksumValidationWhenSupported, fmt.Errorf("invalid value for %q: %q. Valid values are: when_supported, when_required", responseChecksumValidationParamKey, value)
	}
}

// NewDefaultV2Config returns an aws.Config for AWS SDK v2, using the default options.
func NewDefaultV2Config(ctx context.Context) (aws.Config, error) {
	return config.LoadDefaultConfig(ctx)
}

// V2ConfigFromURLParams returns an aws.Config for AWS SDK v2 initialized based on the URL
// parameters in q. It is intended to be used by URLOpeners for AWS services if
// UseV2 returns true.
//
// https://pkg.go.dev/github.com/aws/aws-sdk-go-v2/aws#Config
//
// It returns an error if q contains any unknown query parameters; callers
// should remove any query parameters they know about from q before calling
// V2ConfigFromURLParams.
//
// The following query options are supported:
//   - region: The AWS region for requests; sets WithRegion.
//   - anonymous: A value of "true" forces use of anonymous credentials.
//   - profile: The shared config profile to use; sets SharedConfigProfile.
//   - role: An IAM role ARN to assume via STS.
//   - role_session_name: The session name for the assumed role.
//   - role_external_id: The external ID for the assumed role.
//   - role_duration: The duration of the role session, e.g. "1h".
//   - web_identity_token_file: Path to an OIDC token file; assumes the role with web identity.
//   - endpoint: The AWS service endpoint to send HTTP request.
//   - hostname_immutable: Make the hostname immutable, only works if endpoint is also set.
//   - dualstack: A value of "true" enables dual stack (IPv4 and IPv6) endpoints.
//   - fips: A value of "true" enables the use of FIPS endpoints.
//   - rate_limiter_capacity: A integer value configures the capacity of a token bucket used
//     in client-side rate limits. If no value is set, the client-side rate limiting is disabled.
//     See https://aws.github.io/aws-sdk-go-v2/docs/configuring-sdk/retries-timeouts/#client-side-rate-limiting.
//   - request_checksum_calculation: Request checksum calculation mode (when_supported, when_required)
//   - response_checksum_validation: Response checksum validation mode (when_supported, when_required)
func V2ConfigFromURLParams(ctx context.Context, q url.Values) (aws.Config, error) {
	var endpoint string
	var hostnameImmutable bool
	var rateLimitCapacity int64
	var roleARN string
	var role roleOptions
	var anonymous bool
	var opts []func(*config.LoadOptions) error
	for param, values := range q {
		value := values[0]
		switch param {
		case "hostname_immutable":
			var err error
			hostnameImmutable, err = strconv.ParseBool(value)
			if err != nil {
				return aws.Config{}, fmt.Errorf("invalid value for hostname_immutable: %w", err)
			}
		case "region":
			opts = append(opts, config.WithRegion(value))
		case "endpoint":
			endpoint = value
		case "profile":
			opts = append(opts, config.WithSharedConfigProfile(value))
		case "dualstack":
			dualStack, err := strconv.ParseBool(value)
			if err != nil {
				return aws.Config{}, fmt.Errorf("invalid value for dualstack: %w", err)
			}
			if dualStack {
				opts = append(opts, config.WithUseDualStackEndpoint(aws.DualStackEndpointStateEnabled))
			}
		case "fips":
			fips, err := strconv.ParseBool(value)
			if err != nil {
				return aws.Config{}, fmt.Errorf("invalid value for fips: %w", err)
			}
			if fips {
				opts = append(opts, config.WithUseFIPSEndpoint(aws.FIPSEndpointStateEnabled))
			}
		case "rate_limiter_capacity":
			var err error
			rateLimitCapacity, err = strconv.ParseInt(value, 10, 32)
			if err != nil {
				return aws.Config{}, fmt.Errorf("invalid value for capacity: %w", err)
			}
		case "anonymous":
			anon, err := strconv.ParseBool(value)
			if err != nil {
				return aws.Config{}, fmt.Errorf("invalid value for anonymous: %w", err)
			}
			if anon {
				anonymous = true
				opts = append(opts, config.WithCredentialsProvider(aws.AnonymousCredentials{}))
			}
		case "role":
			if !strings.HasPrefix(value, "arn:") {
				return aws.Config{}, fmt.Errorf("invalid value for role: must be a valid ARN (starts with 'arn:'): %s", value)
			}
			roleARN = value
		case "role_session_name":
			role.sessionName = value
		case "role_external_id":
			role.externalID = value
		case "role_duration":
			d, err := time.ParseDuration(value)
			if err != nil {
				return aws.Config{}, fmt.Errorf("invalid value for role_duration: %w", err)
			}
			role.duration = d
		case "web_identity_token_file":
			role.webIdentityTokenFile = value
		case requestChecksumCalculationParamKey:
			value, err := parseRequestChecksumCalculation(value)
			if err != nil {
				return aws.Config{}, err
			}

			opts = append(opts, config.WithRequestChecksumCalculation(value))
		case responseChecksumValidationParamKey:
			value, err := parseResponseChecksumValidation(value)
			if err != nil {
				return aws.Config{}, err
			}

			opts = append(opts, config.WithResponseChecksumValidation(value))
		case "awssdk":
			// ignore, should be handled before this
		default:
			return aws.Config{}, fmt.Errorf("unknown query parameter %q", param)
		}
	}
	if roleARN == "" && role != (roleOptions{}) {
		return aws.Config{}, fmt.Errorf("query parameter %q is required when using role_session_name, role_external_id, role_duration or web_identity_token_file", "role")
	}
	if roleARN != "" && anonymous {
		return aws.Config{}, fmt.Errorf("query parameter %q is not supported with anonymous credentials", "role")
	}
	if role.webIdentityTokenFile != "" && role.externalID != "" {
		return aws.Config{}, fmt.Errorf("query parameter %q is not supported with web_identity_token_file", "role_external_id")
	}
	if roleARN != "" {
		baseConfig, err := config.LoadDefaultConfig(ctx, opts...)
		if err != nil {
			return aws.Config{}, fmt.Errorf("failed to load default AWS config: %w", err)
		}
		stsClient := sts.NewFromConfig(baseConfig)
		provider := role.provider(stsClient, roleARN)
		opts = []func(*config.LoadOptions) error{
			config.WithCredentialsProvider(provider),
		}
		if baseConfig.Region == "" {
			return aws.Config{}, fmt.Errorf("STS client created with empty region: all other parameters must be collected before assuming role")
		}
		opts = append(opts, config.WithRegion(baseConfig.Region))
	}

	var rateLimiter retry.RateLimiter
	rateLimiter = ratelimit.None
	if rateLimitCapacity > 0 {
		rateLimiter = ratelimit.NewTokenRateLimit(uint(rateLimitCapacity))
	}
	opts = append(opts, config.WithRetryer(func() aws.Retryer {
		return retry.NewStandard(func(so *retry.StandardOptions) {
			so.RateLimiter = rateLimiter
		})
	}))

	cfg, err := config.LoadDefaultConfig(ctx, opts...)
	if err != nil {
		return aws.Config{}, err
	}
	if endpoint != "" {
		cfg.EndpointResolverWithOptions = aws.EndpointResolverWithOptionsFunc(
			func(service, region string, options ...any) (aws.Endpoint, error) {
				return aws.Endpoint{
					PartitionID:       "aws",
					URL:               endpoint,
					SigningRegion:     region,
					HostnameImmutable: hostnameImmutable,
				}, nil
			})
	}
	return cfg, nil
}

// roleOptions holds the optional query parameters for assuming a role.
type roleOptions struct {
	sessionName          string
	externalID           string
	duration             time.Duration
	webIdentityTokenFile string
}

// provider returns a credentials provider that assumes roleARN.
func (r roleOptions) provider(stsClient *sts.Client, roleARN string) aws.CredentialsProvider {
	if r.webIdentityTokenFile != "" {
		return stscreds.NewWebIdentityRoleProvider(stsClient, roleARN, stscreds.IdentityTokenFile(r.webIdentityTokenFile), func(o *stscreds.WebIdentityRoleOptions) {
			if r.sessionName != "" {
				o.RoleSessionName = r.sessionName
			}
			o.Duration = r.duration
		})
	}
	return stscreds.NewAssumeRoleProvider(stsClient, roleARN, func(o *stscreds.AssumeRoleOptions) {
		if r.sessionName != "" {
			o.RoleSessionName = r.sessionName
		}
		if r.externalID != "" {
			o.ExternalID = aws.String(r.externalID)
		}
		o.Duration = r.duration
	})
}
