package leet

import (
	"fmt"
	"net/url"
	"strings"
)

// ParseRemoteURL parses a W&B run URL into RemoteRunParams.
//
// Accepted shapes:
//
//	https://<host>[/<base-path>]/<entity>/<project>/<run-id>
//	https://<host>[/<base-path>]/<entity>/<project>/runs/<run-id>
//
// The base path, if any, is part of the server's base URL. The host is used
// as-is; canonicalization (e.g. mapping an app URL to its API URL) is the
// launcher's responsibility.
func ParseRemoteURL(s string) (*RemoteRunParams, error) {
	u, err := url.Parse(s)
	if err != nil {
		return nil, fmt.Errorf("invalid remote URL %q: %w", s, err)
	}
	if u.Scheme != "http" && u.Scheme != "https" {
		return nil, fmt.Errorf("remote URL must use http(s), got %q", s)
	}
	if u.Host == "" {
		return nil, fmt.Errorf("remote URL is missing host: %q", s)
	}

	parts := strings.Split(strings.Trim(u.Path, "/"), "/")
	n := len(parts)
	var base, run []string
	switch {
	case n >= 4 && parts[n-2] == "runs":
		base, run = parts[:n-4], []string{parts[n-4], parts[n-3], parts[n-1]}
	case n >= 3:
		base, run = parts[:n-3], parts[n-3:]
	}
	if len(run) != 3 || run[0] == "" || run[1] == "" || run[2] == "" {
		return nil, fmt.Errorf(
			"remote URL must be https://<host>/<entity>/<project>/runs/<run-id>, got %q",
			s,
		)
	}

	baseURL := u.Scheme + "://" + u.Host
	if len(base) > 0 {
		baseURL += "/" + strings.Join(base, "/")
	}

	return &RemoteRunParams{
		BaseURL: baseURL,
		Entity:  run[0],
		Project: run[1],
		RunID:   run[2],
	}, nil
}
