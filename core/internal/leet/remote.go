package leet

import (
	"fmt"
	"net/url"
	"strings"
)

// ParseRemoteURL parses a W&B run/project URL into RemoteRunParams.
//
// Accepted shapes (decided client-side, validated again here):
//
//	https://<host>/<entity>/<project>/<run-id>
//	https://<host>/<entity>/<project>/runs/<run-id>
//	https://<host>/<entity>/<project>/sweeps/<sweep-id>
//
// Only run/sweep URLs are supported in this PR; project-only URLs return
// an error here and will be re-enabled when the workspace mode lands.
func ParseRemoteURL(s string) (*RemoteRunParams, error) {
	u, err := url.Parse(s)
	if err != nil {
		return nil, fmt.Errorf("invalid remote URL %q: %w", s, err)
	}
	if u.Scheme != "http" && u.Scheme != "https" {
		return nil, fmt.Errorf("remote URL must use http(s), got %q", u.Scheme)
	}
	if u.Host == "" {
		return nil, fmt.Errorf("remote URL is missing host: %q", s)
	}

	path := strings.ReplaceAll(u.Path, "/runs/", "/")
	path = strings.ReplaceAll(path, "/sweeps/", "/")
	parts := strings.Split(strings.Trim(path, "/"), "/")
	if len(parts) != 3 || parts[0] == "" || parts[1] == "" || parts[2] == "" {
		return nil, fmt.Errorf(
			"remote URL must be https://<host>/<entity>/<project>/<run-id>, got %q",
			s,
		)
	}

	return &RemoteRunParams{
		BaseURL: u.Scheme + "://" + u.Host,
		Entity:  parts[0],
		Project: parts[1],
		RunId:   parts[2],
	}, nil
}
