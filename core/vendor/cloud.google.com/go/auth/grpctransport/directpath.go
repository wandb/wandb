// Copyright 2023 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package grpctransport

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/url"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"cloud.google.com/go/auth"
	"cloud.google.com/go/auth/credentials"
	"cloud.google.com/go/auth/internal"
	"cloud.google.com/go/auth/internal/compute"
	"cloud.google.com/go/compute/metadata"
	"golang.org/x/time/rate"
	"google.golang.org/grpc"
	grpccreds "google.golang.org/grpc/credentials"
	grpcgoogle "google.golang.org/grpc/credentials/google"
)

const (
	directPathInterconnectInfix               = "-direct."
	directPathInterconnectStorageHost         = "storage-direct.googleapis.com"
	directPathInterconnectStoragePreprodHost  = "storage-preprod-direct.sandbox.googleapis.com"
	directPathNotEnabledReason                = "DirectPath is disabled. To enable, please set the EnableDirectPath option along with the EnableDirectPathXds option."
	directPathUnsupportedUniverseReason       = "DirectPath is disabled. Non-default universe domain is not supported."
	directPathUDLookupErrReason               = "DirectPath is disabled. Failed to determine universe domain"
	directPathInterconnectUnsupportedUDReason = "DirectPath over Interconnect is disabled. Non-default universe domain is not supported."
	directPathInterconnectUDLookupErrReason   = "DirectPath over Interconnect is disabled. Failed to determine universe domain"
	directPathInterconnectInvalidCredsReason  = "DirectPath over Interconnect is disabled. Valid credentials are required."
	directPathIncompatibleCredReason          = "DirectPath is disabled. Please make sure the token source is fetched from GCE metadata server and the default service account is used."
	directPathNotOnGCEReason                  = "DirectPath is disabled. DirectPath is only available in a GCE environment."
)

var (
	logRateLimiter = rate.Sometimes{Interval: 1 * time.Second}

	// Assign to var for unit test replacement.
	onComputeEngine = compute.OnComputeEngine

	// Assign to var for unit test replacement.
	metadataUniverseDomain = fetchMetadataUniverseDomain

	// Single-entry cache of ComputeUniverseDomainProvider keyed by
	// GCE_METADATA_HOST. Successful lookups are cached by the provider; errors
	// are not cached so transient failures retry.
	metadataUDProviderMu   sync.Mutex
	metadataUDProviderHost string
	metadataUDProvider     *internal.ComputeUniverseDomainProvider
)

func resetMetadataUniverseDomainCache() {
	metadataUDProviderMu.Lock()
	metadataUDProviderHost = ""
	metadataUDProvider = nil
	metadataUDProviderMu.Unlock()
}

func fetchMetadataUniverseDomain(ctx context.Context) (string, error) {
	host := os.Getenv("GCE_METADATA_HOST")
	metadataUDProviderMu.Lock()
	if metadataUDProvider == nil || metadataUDProviderHost != host {
		metadataUDProviderHost = host
		metadataUDProvider = &internal.ComputeUniverseDomainProvider{
			MetadataClient: metadata.NewClient(nil),
		}
	}
	provider := metadataUDProvider
	metadataUDProviderMu.Unlock()
	return provider.GetProperty(ctx)
}

// interconnectHostAndAuthority returns the DirectPath over Interconnect host
// for host and the :authority override to apply, or "" to keep the authority
// gRPC derives from the target.
//
// Cloud Storage identifies Interconnect traffic by the
// storage-direct.googleapis.com (or, in preprod,
// storage-preprod-direct.sandbox.googleapis.com) :authority and treats RPCs
// sent with the non-direct host as regular traffic, so no override is
// returned for those hosts. Other hosts keep their non-direct authority.
func interconnectHostAndAuthority(host string) (targetHost, authorityOverride string) {
	host = strings.ToLower(host)
	switch {
	case strings.HasSuffix(host, ".googleapis.com") && !strings.Contains(host, directPathInterconnectInfix):
		targetHost = strings.Replace(host, ".", directPathInterconnectInfix, 1)
		authorityOverride = host
	case strings.Contains(host, directPathInterconnectInfix):
		targetHost = host
		authorityOverride = strings.Replace(host, directPathInterconnectInfix, ".", 1)
	default:
		return host, ""
	}
	switch targetHost {
	case directPathInterconnectStorageHost, directPathInterconnectStoragePreprodHost:
		return targetHost, ""
	}
	return targetHost, authorityOverride
}

func parseTarget(endpoint string) (host string, query url.Values, err error) {
	if endpoint == "" {
		return "", nil, errors.New("grpctransport: empty endpoint")
	}
	var target string
	query = url.Values{}
	switch {
	case strings.HasPrefix(endpoint, "google-c2p:///"):
		rest := strings.TrimPrefix(endpoint, "google-c2p:///")
		if strings.ContainsAny(rest, "# \t\r\n") {
			return "", nil, fmt.Errorf("grpctransport: invalid endpoint %q", endpoint)
		}
		var rawQuery string
		var hasQuery bool
		target, rawQuery, hasQuery = strings.Cut(rest, "?")
		if hasQuery {
			query, err = url.ParseQuery(rawQuery)
			if err != nil {
				return "", nil, err
			}
		}
	case strings.HasPrefix(endpoint, "dns:///"):
		target = strings.TrimPrefix(endpoint, "dns:///")
	case strings.Contains(endpoint, "://"):
		return "", nil, fmt.Errorf("grpctransport: unsupported scheme in endpoint %q", endpoint)
	default:
		target = endpoint
	}
	if target == "" || strings.ContainsAny(target, "/?#@ \t\r\n") {
		return "", nil, fmt.Errorf("grpctransport: invalid target %q", endpoint)
	}
	if h, _, splitErr := net.SplitHostPort(target); splitErr == nil {
		if strings.HasPrefix(target, "[") {
			// Reject IPv6 literals and bracketed hostnames.
			return "", nil, fmt.Errorf("grpctransport: invalid host in endpoint %q", endpoint)
		}
		host = h
	} else if strings.Contains(target, ":") {
		// Reject malformed host:port targets and bare IPv6 literals.
		return "", nil, fmt.Errorf("grpctransport: invalid host:port in endpoint %q", endpoint)
	} else {
		host = target
	}
	if host == "" {
		return "", nil, fmt.Errorf("grpctransport: empty host in endpoint %q", endpoint)
	}
	return strings.ToLower(host), query, nil
}

func encodeQuery(v url.Values) string {
	if len(v) == 0 {
		return ""
	}
	var buf strings.Builder
	keys := make([]string, 0, len(v))
	for k := range v {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		vs := v[k]
		keyEscaped := url.QueryEscape(k)
		if len(vs) == 0 {
			if buf.Len() > 0 {
				buf.WriteByte('&')
			}
			buf.WriteString(keyEscaped)
			continue
		}
		for _, val := range vs {
			if buf.Len() > 0 {
				buf.WriteByte('&')
			}
			buf.WriteString(keyEscaped)
			if val != "" {
				buf.WriteByte('=')
				buf.WriteString(url.QueryEscape(val))
			}
		}
	}
	return buf.String()
}

func isDirectPathXdsOverInterconnectUsed(endpoint string, o *Options) bool {
	if valStr, ok := os.LookupEnv(enableDirectPathXdsOverInterconnectEnvVar); ok {
		if b, err := strconv.ParseBool(valStr); err == nil {
			return b
		}
	}
	if o != nil && o.InternalOptions != nil && o.InternalOptions.EnableDirectPathXdsOverInterconnect {
		return true
	}
	if strings.Contains(strings.ToLower(endpoint), directPathInterconnectInfix) || strings.Contains(endpoint, "force-xds") {
		return true
	}
	return false
}

func isGoogleC2PEndpoint(endpoint string) bool {
	return strings.HasPrefix(strings.ToLower(endpoint), "google-c2p:")
}

func hasUniverseDomainHost(endpoint, universeDomain string) bool {
	if universeDomain == "" {
		return false
	}
	host, _, err := parseTarget(endpoint)
	if err != nil {
		return false
	}
	ud := strings.ToLower(universeDomain)
	if host == ud {
		return true
	}
	return strings.HasSuffix(host, "."+ud) && len(host) > len(ud)+1 && !strings.HasPrefix(host, ".") && !strings.Contains(host, "..")
}

func canUseDirectPathWithUniverseDomain(endpoint string, opts *Options) bool {
	if opts == nil || opts.clientUniverseDomain() != internal.DefaultUniverseDomain {
		return false
	}
	return hasUniverseDomainHost(endpoint, internal.DefaultUniverseDomain)
}

func checkDirectPathEnabled(endpoint string, opts *Options) (string, bool) {
	if opts == nil || opts.InternalOptions == nil || !opts.InternalOptions.EnableDirectPath {
		return directPathNotEnabledReason, false
	}
	if !checkDirectPathEndPoint(endpoint) {
		return "", false
	}
	if b, _ := strconv.ParseBool(os.Getenv(disableDirectPathEnvVar)); b {
		return "", false
	}
	if !canUseDirectPathWithUniverseDomain(endpoint, opts) {
		if opts.clientUniverseDomain() == internal.DefaultUniverseDomain {
			host, _, err := parseTarget(endpoint)
			if err != nil || host == "localhost" || net.ParseIP(host) != nil {
				return "", false
			}
		}
		if isDirectPathXdsOverInterconnectUsed(endpoint, opts) {
			return directPathInterconnectUnsupportedUDReason, false
		}
		return directPathUnsupportedUniverseReason, false
	}
	return "", true
}

func isDirectPathEnabled(endpoint string, opts *Options) bool {
	_, ok := checkDirectPathEnabled(endpoint, opts)
	return ok
}

func checkDirectPathEndPoint(endpoint string) bool {
	// Only [dns:///]host[:port] or google-c2p:/// is supported, not other schemes (e.g., "tcp://" or "unix://").
	if strings.Contains(endpoint, "://") &&
		!strings.HasPrefix(endpoint, "dns:///") &&
		!strings.HasPrefix(endpoint, "google-c2p:///") {
		return false
	}

	if endpoint == "" {
		return false
	}

	return true
}

func isTokenProviderComputeEngine(ctx context.Context, tp auth.TokenProvider) bool {
	if tp == nil {
		return false
	}
	tok, err := tp.Token(ctx)
	if err != nil || tok == nil {
		return false
	}
	if tok.MetadataString("auth.google.tokenSource") != "compute-metadata" {
		return false
	}
	if tok.MetadataString("auth.google.serviceAccount") != "default" {
		return false
	}
	return true
}

func isTokenProviderDirectPathCompatible(ctx context.Context, tp auth.TokenProvider, o *Options) bool {
	if tp == nil {
		return false
	}
	if o != nil && o.InternalOptions != nil && o.InternalOptions.EnableNonDefaultSAForDirectPath {
		return true
	}
	return isTokenProviderComputeEngine(ctx, tp)
}

func isDirectPathXdsUsed(o *Options) bool {
	// Method 1: Enable DirectPath xDS by env;
	if b, _ := strconv.ParseBool(os.Getenv(enableDirectPathXdsEnvVar)); b {
		return true
	}
	// Method 2: Enable DirectPath xDS by option;
	if o != nil && o.InternalOptions != nil && o.InternalOptions.EnableDirectPathXds {
		return true
	}
	return false
}

func isDirectPathBoundTokenEnabled(opts *InternalOptions) bool {
	if opts == nil {
		return false
	}
	for _, ev := range opts.AllowHardBoundTokens {
		if ev == "ALTS" {
			return true
		}
	}
	return false
}

// canUseDirectPath reports whether DirectPath can be used for the dial.
// When DirectPath cannot be used, it optionally returns a human-readable
// warning reason explaining the rejection.
func canUseDirectPath(ctx context.Context, endpoint string, opts *Options, creds *auth.Credentials) (string, bool) {
	reason, ok, _ := evaluateDirectPath(ctx, endpoint, opts, creds)
	return reason, ok
}

func evaluateDirectPath(ctx context.Context, endpoint string, opts *Options, creds *auth.Credentials) (reason string, ok bool, isComputeToken bool) {
	if reason, ok := checkDirectPathEnabled(endpoint, opts); !ok {
		return reason, false, false
	}
	interconnect := isDirectPathXdsOverInterconnectUsed(endpoint, opts)
	if creds == nil || creds.TokenProvider == nil {
		if interconnect {
			return directPathInterconnectInvalidCredsReason, false, false
		}
		return directPathIncompatibleCredReason, false, false
	}
	if interconnect {
		ud, err := creds.UniverseDomain(ctx)
		if err != nil {
			return fmt.Sprintf("%s: %v", directPathInterconnectUDLookupErrReason, err), false, false
		}
		if strings.TrimSpace(ud) != internal.DefaultUniverseDomain {
			return directPathInterconnectUnsupportedUDReason, false, false
		}
		// When running on a GCE VM, also verify the VM's metadata server
		// universe domain directly: google-c2p uses ambient ADC (google_default)
		// for its xDS control-plane connection, and credentials without a
		// UniverseDomainProvider default to googleapis.com.
		if onComputeEngine() {
			mdUD, err := metadataUniverseDomain(ctx)
			if err != nil {
				return fmt.Sprintf("%s: %v", directPathInterconnectUDLookupErrReason, err), false, false
			}
			if strings.TrimSpace(mdUD) != internal.DefaultUniverseDomain {
				return directPathInterconnectUnsupportedUDReason, false, false
			}
		}
		return "", true, false
	}
	if !onComputeEngine() {
		return directPathNotOnGCEReason, false, false
	}
	ud, err := creds.UniverseDomain(ctx)
	if err != nil {
		return fmt.Sprintf("%s: %v", directPathUDLookupErrReason, err), false, false
	}
	if strings.TrimSpace(ud) != internal.DefaultUniverseDomain {
		return directPathUnsupportedUniverseReason, false, false
	}
	if opts == nil || opts.InternalOptions == nil || !opts.InternalOptions.EnableNonDefaultSAForDirectPath {
		if !isTokenProviderComputeEngine(ctx, creds) {
			return directPathIncompatibleCredReason, false, false
		}
		isComputeToken = true
	}
	// Verify the GCE metadata server universe domain directly and fail closed
	// on error. Even when creds.UniverseDomain returns googleapis.com (for
	// example, credentials created without a UniverseDomainProvider such as
	// option.WithTokenSource(google.ComputeTokenSource("")), credentials adapted
	// via oauth2adapt from a google.Credentials without a UniverseDomainProvider,
	// or a GDU SA key with EnableNonDefaultSAForDirectPath on a non-GDU VM),
	// GCE DirectPath must never be enabled on a non-GDU GCE VM.
	mdUD, err := metadataUniverseDomain(ctx)
	if err != nil {
		return fmt.Sprintf("%s: %v", directPathUDLookupErrReason, err), false, false
	}
	if strings.TrimSpace(mdUD) != internal.DefaultUniverseDomain {
		return directPathUnsupportedUniverseReason, false, false
	}
	return "", true, isComputeToken
}

// interconnectCredentials is a grpccreds.Bundle that negotiates TLS in every
// mode.
//
// The Google Default bundle selects ALTS for every xDS cluster whose name is
// not prefixed "google_cfe_", which includes the regional DirectPath over
// Interconnect clusters, and ALTS is unavailable outside Google Cloud. A
// bundle, rather than grpc.WithTransportCredentials plus
// grpc.WithPerRPCCredentials, keeps the per-RPC credentials on the channel
// credentials, which are the only credentials gRPC's RLS control channel
// inherits from the parent channel.
type interconnectCredentials struct {
	transportCreds grpccreds.TransportCredentials
	perRPCCreds    grpccreds.PerRPCCredentials
}

func newInterconnectCredentials(perRPCCreds grpccreds.PerRPCCredentials) *interconnectCredentials {
	return &interconnectCredentials{
		transportCreds: grpccreds.NewTLS(nil),
		perRPCCreds:    perRPCCreds,
	}
}

func (c *interconnectCredentials) TransportCredentials() grpccreds.TransportCredentials {
	return c.transportCreds
}

func (c *interconnectCredentials) PerRPCCredentials() grpccreds.PerRPCCredentials {
	return c.perRPCCreds
}

// NewWithMode returns a bundle with cloned TLS transport credentials and the
// same per-RPC credentials regardless of mode. The RLS control channel requests
// fallback mode, and grpclb modes are unused with the google-c2p resolver.
func (c *interconnectCredentials) NewWithMode(string) (grpccreds.Bundle, error) {
	return &interconnectCredentials{
		transportCreds: c.transportCreds.Clone(),
		perRPCCreds:    c.perRPCCreds,
	}, nil
}

// directPathCredentialsBundle returns the credentials bundle for a DirectPath
// channel: TLS-only credentials over Interconnect, or the Google Default bundle
// (with ALTS hard-bound tokens when enabled) otherwise.
func directPathCredentialsBundle(ctx context.Context, interconnect bool, opts *Options, endpoint string, creds *auth.Credentials, perRPCCreds grpccreds.PerRPCCredentials) (grpccreds.Bundle, error) {
	return directPathCredentialsBundleWithComputeCheck(ctx, interconnect, opts, endpoint, creds, perRPCCreds, false)
}

func directPathCredentialsBundleWithComputeCheck(ctx context.Context, interconnect bool, opts *Options, endpoint string, creds *auth.Credentials, perRPCCreds grpccreds.PerRPCCredentials, knownComputeToken bool) (grpccreds.Bundle, error) {
	if interconnect {
		return newInterconnectCredentials(perRPCCreds), nil
	}
	defaultCredentialsOptions := grpcgoogle.DefaultCredentialsOptions{
		PerRPCCreds: perRPCCreds,
	}
	if opts != nil && isDirectPathBoundTokenEnabled(opts.InternalOptions) && creds != nil && creds.TokenProvider != nil && (knownComputeToken || isTokenProviderComputeEngine(ctx, creds)) {
		optsClone := opts.resolveDetectOptions()
		optsClone.TokenBindingType = credentials.ALTSHardBinding
		altsCreds, err := credentials.DetectDefault(optsClone)
		if err != nil {
			return nil, err
		}
		defaultCredentialsOptions.ALTSPerRPCCreds = &grpcCredentialsProvider{
			creds:                altsCreds,
			endpoint:             endpoint,
			clientUniverseDomain: opts.UniverseDomain,
		}
	}
	return grpcgoogle.NewDefaultCredentialsWithOptions(defaultCredentialsOptions), nil
}

// configureDirectPath returns some dial options and an endpoint to use if the
// configuration allows the use of direct path. If it does not the provided
// grpcOpts and endpoint are returned, except that an explicit google-c2p
// endpoint returns an error so it is never dialed without passing DirectPath
// gating.
func configureDirectPath(ctx context.Context, grpcOpts []grpc.DialOption, opts *Options, endpoint string, creds *auth.Credentials, metadata map[string]string) ([]grpc.DialOption, string, error) {
	reason, ok, isComputeToken := evaluateDirectPath(ctx, endpoint, opts, creds)
	if !ok {
		if reason != "" && opts != nil && (isDirectPathXdsUsed(opts) || isDirectPathXdsOverInterconnectUsed(endpoint, opts)) {
			logRateLimiter.Do(func() {
				logDirectPathMisconfig(opts, endpoint, reason)
			})
		}
		if isGoogleC2PEndpoint(endpoint) {
			if reason != "" {
				return nil, "", fmt.Errorf("grpctransport: %s", reason)
			}
			return nil, "", fmt.Errorf("grpctransport: DirectPath is disabled for endpoint %q", endpoint)
		}
		return grpcOpts, endpoint, nil
	}
	interconnect := isDirectPathXdsOverInterconnectUsed(endpoint, opts)
	// Overwrite all of the previously specific DialOptions, DirectPath uses its own set of credentials and certificates.
	perRPCCreds := &grpcCredentialsProvider{
		creds:    creds,
		endpoint: endpoint,
		metadata: metadata,
	}
	if opts != nil {
		perRPCCreds.clientUniverseDomain = opts.UniverseDomain
	}
	bundle, err := directPathCredentialsBundleWithComputeCheck(ctx, interconnect, opts, endpoint, creds, perRPCCreds, isComputeToken)
	if err != nil {
		return nil, "", err
	}
	grpcOpts = []grpc.DialOption{grpc.WithCredentialsBundle(bundle)}
	if timeoutDialerOption != nil {
		grpcOpts = append(grpcOpts, timeoutDialerOption)
	}
	cleanAddr, query, err := parseTarget(endpoint)
	if err != nil {
		return nil, "", err
	}
	if interconnect {
		var authorityOverride string
		cleanAddr, authorityOverride = interconnectHostAndAuthority(cleanAddr)
		if authorityOverride != "" {
			grpcOpts = append(grpcOpts, grpc.WithAuthority(authorityOverride))
		}
	}
	// Check if google-c2p resolver is enabled for DirectPath
	if strings.HasPrefix(endpoint, "google-c2p:///") {
		if interconnect {
			if !query.Has("force-xds") {
				query["force-xds"] = nil
			}
		}
		endpoint = "google-c2p:///" + cleanAddr
		if q := encodeQuery(query); q != "" {
			endpoint += "?" + q
		}
	} else if isDirectPathXdsUsed(opts) || interconnect {
		endpoint = "google-c2p:///" + cleanAddr
		if interconnect {
			endpoint += "?force-xds"
		}
	} else {
		if !strings.HasPrefix(endpoint, "dns:///") {
			endpoint = "dns:///" + endpoint
		}
		grpcOpts = append(grpcOpts,
			// For now all DirectPath go clients will be using the following lb config, but in future
			// when different services need different configs, then we should change this to a
			// per-service config.
			grpc.WithDisableServiceConfig(),
			grpc.WithDefaultServiceConfig(`{"loadBalancingConfig":[{"grpclb":{"childPolicy":[{"pick_first":{}}]}}]}`))
	}
	// TODO: add support for system parameters (quota project, request reason) via chained interceptor.
	return grpcOpts, endpoint, nil
}

func logDirectPathMisconfig(o *Options, endpoint, reason string) {
	if o == nil || reason == "" {
		return
	}
	if !isDirectPathXdsUsed(o) && !isDirectPathXdsOverInterconnectUsed(endpoint, o) {
		return
	}
	o.logger().Warn(reason)
}
