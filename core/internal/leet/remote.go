package leet

import (
	"fmt"
	"net/url"
	"strings"
)

// ParseRemoteURL parses a W&B project or run URL into RemoteRunParams.
//
// A URL whose path is <entity>/<project>/runs/<run-id>, optionally followed
// by more segments, names a run. Any other path under <entity>/<project>,
// such as the project's /workspace page, names the project.
//
// The host is used as-is; canonicalization (e.g. wandb.ai -> api.wandb.ai)
// is the launcher's responsibility.
func ParseRemoteURL(s string) (*RemoteRunParams, error) {
	return parseRemoteURL(s, false)
}

// ParseRemoteScopeURL also accepts /orgs/<org> and /<team> compute scopes.
func ParseRemoteScopeURL(s string) (*RemoteRunParams, error) {
	return parseRemoteURL(s, true)
}

func parseRemoteURL(s string, allowScope bool) (*RemoteRunParams, error) {
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
	baseURL := u.Scheme + "://" + u.Host
	if allowScope {
		switch {
		case len(parts) == 1 && parts[0] != "" && parts[0] != "orgs":
			return &RemoteRunParams{BaseURL: baseURL, Entity: parts[0]}, nil
		case len(parts) == 2 && parts[0] == "orgs" && parts[1] != "":
			return &RemoteRunParams{BaseURL: baseURL, Org: parts[1]}, nil
		}
		if parts[0] == "orgs" {
			return nil, fmt.Errorf("organization URL must be https://<host>/orgs/<org>, got %q", s)
		}
	}
	if len(parts) < 2 || parts[0] == "" || parts[1] == "" {
		return nil, fmt.Errorf(
			"remote URL must be https://<host>/<entity>/<project> or "+
				"https://<host>/<entity>/<project>/runs/<run-id>, got %q",
			s,
		)
	}

	params := &RemoteRunParams{
		BaseURL: baseURL,
		Entity:  parts[0],
		Project: parts[1],
	}
	if len(parts) >= 4 && parts[2] == "runs" {
		params.RunID = parts[3]
	}
	return params, nil
}
