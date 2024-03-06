// Defines W&B settings.
package settings

import (
	"fmt"
	"net/url"

	"github.com/wandb/wandb/core/pkg/auth"
	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

// Settings for the SDK.
//
// This is derived from the Settings proto and adapted for use in Go.
type Settings struct {
	// The W&B API key.
	//
	// This can be empty if we're in offline mode.
	APIKey string

	// The ID of the run.
	RunID string

	// The W&B URL where the run can be viewed.
	RunURL string

	// The W&B project ID.
	Project string

	// The W&B entity, like a user or a team.
	Entity string

	// The directory for storing log files.
	LogDir string

	// Filename to use for internal logs.
	InternalLogFile string

	// The source proto.
	//
	// DO NOT ADD USAGES. Used to refactor incrementally.
	Proto *service.Settings
}

// Parses the Settings proto into a Settings object.
func Parse(proto *service.Settings) *Settings {
	return &Settings{
		APIKey:          proto.GetApiKey().GetValue(),
		RunID:           proto.GetRunId().GetValue(),
		RunURL:          proto.GetRunUrl().GetValue(),
		Project:         proto.GetProject().GetValue(),
		Entity:          proto.GetEntity().GetValue(),
		LogDir:          proto.GetLogDir().GetValue(),
		InternalLogFile: proto.GetLogInternal().GetValue(),
		Proto:           proto,
	}
}

// Ensures the APIKey is set if it needs to be.
//
// Reads the API key from .netrc if it's not already set.
func (s *Settings) EnsureAPIKey() error {
	if s.Proto.GetApiKey().GetValue() != "" ||
		s.Proto.GetXOffline().GetValue() {
		return nil
	}

	baseUrl := s.Proto.GetBaseUrl().GetValue()
	u, err := url.Parse(baseUrl)
	if err != nil {
		return fmt.Errorf("settings: failed to parse base URL: %v", err)
	}

	host := u.Hostname()
	_, password, err := auth.GetNetrcLogin(host)
	if err != nil {
		return fmt.Errorf("settings: failed to get API key from netrc: %v", err)
	}
	s.Proto.ApiKey = &wrapperspb.StringValue{Value: password}

	return nil
}
