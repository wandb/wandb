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

	// The source proto.
	//
	// DO NOT ADD USAGES. Used to refactor incrementally.
	Proto *service.Settings
}

// Parses the Settings proto into a Settings object.
func From(proto *service.Settings) *Settings {
	return &Settings{Proto: proto}
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

// The W&B API key.
//
// This can be empty if we're in offline mode.
func (s *Settings) GetAPIKey() string {
	return s.Proto.ApiKey.GetValue()
}

// The ID of the run.
func (s *Settings) GetRunID() string {
	return s.Proto.RunId.GetValue()
}

// The W&B URL where the run can be viewed.
func (s *Settings) GetRunURL() string {
	return s.Proto.RunUrl.GetValue()
}

// The W&B project ID.
func (s *Settings) GetProject() string {
	return s.Proto.Project.GetValue()
}

// The W&B entity, like a user or a team.
func (s *Settings) GetEntity() string {
	return s.Proto.Entity.GetValue()
}

// The directory for storing log files.
func (s *Settings) GetLogDir() string {
	return s.Proto.LogDir.GetValue()
}

// Filename to use for internal logs.
func (s *Settings) GetInternalLogFile() string {
	return s.Proto.LogInternal.GetValue()
}

// The local directory where the run's files are stored.
func (s *Settings) GetFilesDir() string {
	return s.Proto.FilesDir.GetValue()
}
