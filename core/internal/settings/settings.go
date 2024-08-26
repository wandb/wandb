// Defines W&B settings.
package settings

import (
	"fmt"
	"net/url"
	"time"

	"github.com/wandb/wandb/core/internal/auth"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

// Settings for the SDK.
//
// This is derived from the Settings proto and adapted for use in Go.
type Settings struct {

	// The source proto.
	//
	// DO NOT ADD USAGES. Used to refactor incrementally.
	Proto *spb.Settings
}

// Parses the Settings proto into a Settings object.
func From(proto *spb.Settings) *Settings {
	return &Settings{Proto: proto}
}

// Ensures the APIKey is set if it needs to be.
//
// Reads the API key from .netrc if it's not already set.
func (s *Settings) EnsureAPIKey() error {
	if s.GetAPIKey() != "" || s.IsOffline() {
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

// Whether we are in sync mode.
func (s *Settings) IsSync() bool {
	return s.Proto.XSync.GetValue()
}

// Whether we are in offline mode.
func (s *Settings) IsOffline() bool {
	return s.Proto.XOffline.GetValue()
}

// Whether we are in shared mode.
//
// In "shared" mode, multiple processes can write to the same run,
// for example from different machines.
func (s *Settings) IsSharedMode() bool {
	return s.Proto.XShared.GetValue()
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

// The W&B user name.
func (s *Settings) GetUserName() string {
	return s.Proto.Username.GetValue()
}

// The W&B email address.
func (s *Settings) GetEmail() string {
	return s.Proto.Email.GetValue()
}

// The W&B sweep URL.
func (s *Settings) GetSweepURL() string {
	return s.Proto.SweepUrl.GetValue()
}

func (s *Settings) GetBaseURL() string {
	return s.Proto.BaseUrl.GetValue()
}

// The start time of the run.
func (s *Settings) GetStartTime() time.Time {
	seconds := s.Proto.XStartTime.GetValue()
	return time.UnixMicro(int64(seconds * 1e6))
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

// Unix glob patterns relative to `files_dir` to not upload.
func (s *Settings) GetIgnoreGlobs() []string {
	return s.Proto.IgnoreGlobs.GetValue()
}

// An approximate maximum request size for the filestream API.
func (s *Settings) GetFileStreamMaxBytes() int32 {
	return s.Proto.XFileStreamMaxBytes.GetValue()
}

// Additional headers to add to all outgoing HTTP requests.
func (s *Settings) GetExtraHTTPHeaders() map[string]string {
	return s.Proto.XExtraHttpHeaders.GetValue()
}

// Maximum number of retries for filestream operations.
func (s *Settings) GetFileStreamMaxRetries() int32 {
	return s.Proto.XFileStreamRetryMax.GetValue()
}

// Initial wait in-between filestream retries.
func (s *Settings) GetFileStreamRetryWaitMin() time.Duration {
	return time.Second * time.Duration(
		s.Proto.XFileStreamRetryWaitMinSeconds.GetValue())
}

// Final wait in-between filestream retries.
func (s *Settings) GetFileStreamRetryWaitMax() time.Duration {
	return time.Second * time.Duration(
		s.Proto.XFileStreamRetryWaitMaxSeconds.GetValue())
}

// Per-retry timeout for filestream operations.
func (s *Settings) GetFileStreamTimeout() time.Duration {
	return time.Second * time.Duration(
		s.Proto.XFileStreamTimeoutSeconds.GetValue())
}

// Maximum number of retries for file upload/download operations.
func (s *Settings) GetFileTransferMaxRetries() int32 {
	return s.Proto.XFileTransferRetryMax.GetValue()
}

// Initial wait in-between file upload/download retries.
func (s *Settings) GetFileTransferRetryWaitMin() time.Duration {
	return time.Second * time.Duration(
		s.Proto.XFileTransferRetryWaitMinSeconds.GetValue())
}

// Final wait in-between file upload/download retries.
func (s *Settings) GetFileTransferRetryWaitMax() time.Duration {
	return time.Second * time.Duration(
		s.Proto.XFileTransferRetryWaitMaxSeconds.GetValue())
}

// Per-retry timeout for file upload/download operations.
func (s *Settings) GetFileTransferTimeout() time.Duration {
	return time.Second * time.Duration(
		s.Proto.XFileTransferTimeoutSeconds.GetValue())
}

// Maximum number of retries for GraphQL operations.
func (s *Settings) GetGraphQLMaxRetries() int32 {
	return s.Proto.XGraphqlRetryMax.GetValue()
}

// Initial wait in-between GraphQL retries.
func (s *Settings) GetGraphQLRetryWaitMin() time.Duration {
	return time.Second * time.Duration(
		s.Proto.XGraphqlRetryWaitMinSeconds.GetValue())
}

// Final wait in-between GraphQL retries.
func (s *Settings) GetGraphQLRetryWaitMax() time.Duration {
	return time.Second * time.Duration(
		s.Proto.XGraphqlRetryWaitMaxSeconds.GetValue())
}

// Per-retry timeout for GraphQL operations.
func (s *Settings) GetGraphQLTimeout() time.Duration {
	return time.Second * time.Duration(
		s.Proto.XGraphqlTimeoutSeconds.GetValue())
}

// Custom proxy for http requests to W&B.
func (s *Settings) GetHTTPProxy() string {
	return s.Proto.HttpProxy.GetValue()
}

// Custom proxy for https requests to W&B.
func (s *Settings) GetHTTPSProxy() string {
	return s.Proto.HttpsProxy.GetValue()
}

// Resume mode for the run.
func (s *Settings) GetResume() string {
	return s.Proto.Resume.GetValue()
}

// ResumeFrom (or Rewind) information for the run.
func (s *Settings) GetResumeFrom() *spb.RunMoment {
	return s.Proto.ResumeFrom
}

// Fork information for the run.
func (s *Settings) GetForkFrom() *spb.RunMoment {
	return s.Proto.ForkFrom
}
