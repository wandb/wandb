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
//	https://<host>/<entity>/<project>/<run-id>
//	https://<host>/<entity>/<project>/runs/<run-id>
//
// The host is used as-is; canonicalization (e.g. wandb.ai -> api.wandb.ai)
// is the launcher's responsibility. Forge API URLs include /api/wandb before
// the run path.
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

	baseURL := u.Scheme + "://" + u.Host
	runPath := u.Path
	if strings.EqualFold(u.Hostname(), "forge.coreweave.com") ||
		strings.EqualFold(u.Hostname(), "qa.forge.coreweave.com") {
		const apiPath = "/api/wandb"
		if u.Scheme != "https" || u.User != nil ||
			(u.Port() != "" && u.Port() != "443") ||
			!strings.HasPrefix(runPath, apiPath+"/") {
			return nil, fmt.Errorf("Forge remote URL must use https://<host>%s/<entity>/<project>/runs/<run-id>, got %q", apiPath, s)
		}
		baseURL += apiPath
		runPath = strings.TrimPrefix(runPath, apiPath)
	}

	parts := strings.Split(strings.Trim(runPath, "/"), "/")
	if len(parts) == 4 && parts[2] == "runs" {
		parts = []string{parts[0], parts[1], parts[3]}
	}
	if len(parts) != 3 || parts[0] == "" || parts[1] == "" || parts[2] == "" {
		return nil, fmt.Errorf(
			"remote URL must be https://<host>/<entity>/<project>/runs/<run-id>, got %q",
			s,
		)
	}

	return &RemoteRunParams{
		BaseURL: baseURL,
		Entity:  parts[0],
		Project: parts[1],
		RunID:   parts[2],
	}, nil
}
