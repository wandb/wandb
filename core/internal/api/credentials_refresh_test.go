package api_test

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"golang.org/x/sync/errgroup"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/apitest"
	"github.com/wandb/wandb/core/internal/httplayerstest"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	wbsettings "github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func expiredAt() string {
	return time.Now().UTC().Add(-time.Hour).Format("2006-01-02 15:04:05")
}

func writeCredentialsFile(t *testing.T, dir string, host string, refreshToken string) string {
	t.Helper()
	path := filepath.Join(dir, "credentials.json")
	contents := fmt.Sprintf(`{
  "credentials": {
    %q: {
      "expires_at": %q,
      "access_token": "stale-access-token",
      "refresh_token": %q
    }
  }
}`, host, expiredAt(), refreshToken)
	require.NoError(t, os.WriteFile(path, []byte(contents), 0o600))
	return path
}

func readCredentialsFile(t *testing.T, path string) map[string]map[string]string {
	t.Helper()
	contents, err := os.ReadFile(path)
	require.NoError(t, err)

	var parsed struct {
		Credentials map[string]map[string]string `json:"credentials"`
	}
	require.NoError(t, json.Unmarshal(contents, &parsed))
	return parsed.Credentials
}

// rotatingAuthServer returns a new access token and refresh token on every exchange.
func rotatingAuthServer(t *testing.T) (*apitest.RecordingServer, *atomic.Int64) {
	t.Helper()
	var exchanges atomic.Int64
	server := apitest.NewRecordingServer(apitest.WithHandlerFunc(
		func(w http.ResponseWriter, req *http.Request) {
			n := exchanges.Add(1)
			w.Header().Set("Content-Type", "application/json")
			require.NoError(t, json.NewEncoder(w).Encode(map[string]any{
				"access_token":  fmt.Sprintf("wb_at_%d", n),
				"refresh_token": fmt.Sprintf("wb_rt_%d", n),
				"expires_in":    time.Hour.Seconds(),
			}))
		}))
	return server, &exchanges
}

func browserLoginSettings(host string, credentialsFile string) *wbsettings.Settings {
	return wbsettings.From(&spb.Settings{
		BaseUrl:         &wrapperspb.StringValue{Value: host},
		CredentialsFile: &wrapperspb.StringValue{Value: credentialsFile},
	})
}

func TestBrowserLoginRefreshesWithTheStoredToken(t *testing.T) {
	server, _ := rotatingAuthServer(t)
	defer server.Close()
	credentialsFile := writeCredentialsFile(t, t.TempDir(), server.URL, "wb_rt_stored")

	provider, err := api.NewCredentialProvider(
		browserLoginSettings(server.URL, credentialsFile),
		observabilitytest.NewTestLogger(t).Logger,
	)
	require.NoError(t, err)

	reqs, err := httplayerstest.MapRequest(t, provider, exampleGetRequest(t))
	require.NoError(t, err)
	require.Len(t, reqs, 1)
	assert.Equal(t, "Bearer wb_at_1", reqs[0].Header.Get("Authorization"))

	exchanges := server.Requests()
	require.Len(t, exchanges, 1)
	form, err := url.ParseQuery(string(exchanges[0].Body))
	require.NoError(t, err)
	assert.Equal(t, "refresh_token", form.Get("grant_type"))
	assert.Equal(t, "wb_rt_stored", form.Get("refresh_token"))
	assert.Equal(t, api.CLIClientID, form.Get("client_id"))
}

func TestBrowserLoginPersistsTheReplacementRefreshToken(t *testing.T) {
	server, _ := rotatingAuthServer(t)
	defer server.Close()
	credentialsFile := writeCredentialsFile(t, t.TempDir(), server.URL, "wb_rt_stored")

	provider, err := api.NewCredentialProvider(
		browserLoginSettings(server.URL, credentialsFile),
		observabilitytest.NewTestLogger(t).Logger,
	)
	require.NoError(t, err)

	_, err = httplayerstest.MapRequest(t, provider, exampleGetRequest(t))
	require.NoError(t, err)

	stored := readCredentialsFile(t, credentialsFile)[server.URL]
	assert.Equal(t, "wb_rt_1", stored["refresh_token"])
	assert.Equal(t, "wb_at_1", stored["access_token"])
}

func TestBrowserLoginLeavesOtherHostsAlone(t *testing.T) {
	server, _ := rotatingAuthServer(t)
	defer server.Close()

	dir := t.TempDir()
	credentialsFile := filepath.Join(dir, "credentials.json")
	contents := fmt.Sprintf(`{
  "credentials": {
    %q: {
      "expires_at": %q,
      "access_token": "stale-access-token",
      "refresh_token": "wb_rt_stored"
    },
    "https://other.example.com": {
      "expires_at": "2099-01-01 00:00:00",
      "access_token": "other-access-token",
      "refresh_token": "other-refresh-token"
    }
  }
}`, server.URL, expiredAt())
	require.NoError(t, os.WriteFile(credentialsFile, []byte(contents), 0o600))

	provider, err := api.NewCredentialProvider(
		browserLoginSettings(server.URL, credentialsFile),
		observabilitytest.NewTestLogger(t).Logger,
	)
	require.NoError(t, err)

	_, err = httplayerstest.MapRequest(t, provider, exampleGetRequest(t))
	require.NoError(t, err)

	other := readCredentialsFile(t, credentialsFile)["https://other.example.com"]
	assert.Equal(t, "other-refresh-token", other["refresh_token"])
	assert.Equal(t, "other-access-token", other["access_token"])
}

func TestBrowserLoginKeepsTheReplacementWhenItCannotBeSaved(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("root ignores directory permissions")
	}

	// Inside the 5-minute window, so every request refreshes.
	var exchanges atomic.Int64
	server := apitest.NewRecordingServer(apitest.WithHandlerFunc(
		func(w http.ResponseWriter, req *http.Request) {
			n := exchanges.Add(1)
			w.Header().Set("Content-Type", "application/json")
			require.NoError(t, json.NewEncoder(w).Encode(map[string]any{
				"access_token":  fmt.Sprintf("wb_at_%d", n),
				"refresh_token": fmt.Sprintf("wb_rt_%d", n),
				"expires_in":    time.Minute.Seconds(),
			}))
		}))
	defer server.Close()

	dir := t.TempDir()
	credentialsFile := writeCredentialsFile(t, dir, server.URL, "wb_rt_stored")

	// Readable, but nothing new can be created beside the file.
	require.NoError(t, os.Chmod(dir, 0o500))
	t.Cleanup(func() { _ = os.Chmod(dir, 0o700) })

	provider, err := api.NewCredentialProvider(
		browserLoginSettings(server.URL, credentialsFile),
		observabilitytest.NewTestLogger(t).Logger,
	)
	require.NoError(t, err)

	for range 2 {
		_, err = httplayerstest.MapRequest(t, provider, exampleGetRequest(t))
		require.NoError(t, err)
	}

	requests := server.Requests()
	require.Len(t, requests, 2)
	form, err := url.ParseQuery(string(requests[1].Body))
	require.NoError(t, err)
	assert.Equal(t, "wb_rt_1", form.Get("refresh_token"))
}

func TestBrowserLoginRejectsAnIncompleteResponse(t *testing.T) {
	testCases := []struct {
		name     string
		response map[string]any
		wantErr  string
	}{
		{
			name: "no replacement refresh token",
			response: map[string]any{
				"access_token": "wb_at_1",
				"expires_in":   time.Hour.Seconds(),
			},
			wantErr: "replacement refresh token",
		},
		{
			name: "no access token",
			response: map[string]any{
				"refresh_token": "wb_rt_1",
				"expires_in":    time.Hour.Seconds(),
			},
			wantErr: "access token",
		},
		{
			name: "no expires_in",
			response: map[string]any{
				"access_token":  "wb_at_1",
				"refresh_token": "wb_rt_1",
			},
			wantErr: "expires_in",
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			server := apitest.NewRecordingServer(apitest.WithHandlerFunc(
				func(w http.ResponseWriter, req *http.Request) {
					w.Header().Set("Content-Type", "application/json")
					require.NoError(t, json.NewEncoder(w).Encode(tc.response))
				}))
			defer server.Close()
			credentialsFile := writeCredentialsFile(
				t, t.TempDir(), server.URL, "wb_rt_stored")

			provider, err := api.NewCredentialProvider(
				browserLoginSettings(server.URL, credentialsFile),
				observabilitytest.NewTestLogger(t).Logger,
			)
			require.NoError(t, err)

			_, err = httplayerstest.MapRequest(t, provider, exampleGetRequest(t))
			require.ErrorContains(t, err, tc.wantErr)
		})
	}
}

func TestBrowserLoginOnlyRefreshesOnceAcrossProviders(t *testing.T) {
	server, exchanges := rotatingAuthServer(t)
	defer server.Close()
	credentialsFile := writeCredentialsFile(t, t.TempDir(), server.URL, "wb_rt_stored")

	var group errgroup.Group
	for range 4 {
		group.Go(func() error {
			provider, err := api.NewCredentialProvider(
				browserLoginSettings(server.URL, credentialsFile),
				observabilitytest.NewTestLogger(t).Logger,
			)
			if err != nil {
				return err
			}
			_, err = httplayerstest.MapRequest(t, provider, exampleGetRequest(t))
			return err
		})
	}
	require.NoError(t, group.Wait())

	assert.Equal(t, int64(1), exchanges.Load())
}

func TestBrowserLoginIsNotUsedWhenAnAPIKeyIsSet(t *testing.T) {
	server, exchanges := rotatingAuthServer(t)
	defer server.Close()
	credentialsFile := writeCredentialsFile(t, t.TempDir(), server.URL, "wb_rt_stored")

	provider, err := api.NewCredentialProvider(
		wbsettings.From(&spb.Settings{
			ApiKey:          &wrapperspb.StringValue{Value: "test-api-key"},
			BaseUrl:         &wrapperspb.StringValue{Value: server.URL},
			CredentialsFile: &wrapperspb.StringValue{Value: credentialsFile},
		}),
		observabilitytest.NewTestLogger(t).Logger,
	)
	require.NoError(t, err)

	reqs, err := httplayerstest.MapRequest(t, provider, exampleGetRequest(t))
	require.NoError(t, err)
	require.Len(t, reqs, 1)
	assert.Equal(t, "Basic YXBpOnRlc3QtYXBpLWtleQ==", reqs[0].Header.Get("Authorization"))
	assert.Equal(t, int64(0), exchanges.Load())
}

func TestBrowserLoginAbsentIsNotAnError(t *testing.T) {
	provider, err := api.NewCredentialProvider(
		browserLoginSettings(
			"https://api.wandb.ai",
			filepath.Join(t.TempDir(), "credentials.json"),
		),
		observabilitytest.NewTestLogger(t).Logger,
	)

	require.NoError(t, err)
	assert.Equal(t, api.NoopCredentialProvider{}, provider)
}
