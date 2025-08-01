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

// Creates a new Settings object.
func New() *Settings {
	return &Settings{Proto: &spb.Settings{}}
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

// Path to file containing an identity token for authentication.
func (s *Settings) GetIdentityTokenFile() string {
	return s.Proto.IdentityTokenFile.GetValue()
}

// Path to file for writing temporary access tokens.
func (s *Settings) GetCredentialsFile() string {
	return s.Proto.CredentialsFile.GetValue()
}

// Whether we are in silent mode.
func (s *Settings) IsSilent() bool {
	return s.Proto.Silent.GetValue()
}

// Whether we are in offline mode.
func (s *Settings) IsOffline() bool {
	return s.Proto.XOffline.GetValue()
}

// Whether we are syncing a run from the transaction log.
func (s *Settings) IsSync() bool {
	return s.Proto.XSync.GetValue()
}

// Path to the transaction log file, that is being synced.
func (s *Settings) GetTransactionLogPath() string {
	return s.Proto.SyncFile.GetValue()
}

// Whether to skip saving the run events to the transaction log.
//
// This is only relevant for online runs. Can be used to reduce the
// amount of data written to disk.
//
// Should be used with caution, as it removes the gurantees about
// recoverability.
func (s *Settings) IsSkipTransactionLog() bool {
	return s.Proto.XSkipTransactionLog.GetValue()
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

// The name of the run.
func (s *Settings) GetDisplayName() string {
	return s.Proto.RunName.GetValue()
}

// The start time of the run in microseconds since the Unix epoch.
func (s *Settings) GetStartTime() time.Time {
	seconds := s.Proto.XStartTime.GetValue()
	return time.UnixMicro(int64(seconds * 1e6))
}

// The hostname of the machine running the run.
func (s *Settings) GetHostname() string {
	return s.Proto.Host.GetValue()
}

// The root directory that will be used to derive other paths.
// Such as the wandb directory, and the run directory.
//
// By default, this is the current working directory.
func (s *Settings) GetRootDir() string {
	return s.Proto.RootDir.GetValue()
}

// The directory for storing log files.
func (s *Settings) GetLogDir() string {
	return s.Proto.LogDir.GetValue()
}

// Filename to use for internal logs.
func (s *Settings) GetInternalLogFile() string {
	return s.Proto.LogInternal.GetValue()
}

// Absolute path to the local directory where this run's files are stored.
func (s *Settings) GetFilesDir() string {
	return s.Proto.FilesDir.GetValue()
}

// Unix glob patterns relative to `files_dir` to not upload.
func (s *Settings) GetIgnoreGlobs() []string {
	return s.Proto.IgnoreGlobs.GetValue()
}

// The directory for syncing the run from the transaction log.
func (s *Settings) GetSyncDir() string {
	return s.Proto.SyncDir.GetValue()
}

// The URL for the W&B backend.
//
// Used for GraphQL and "filestream" operations.
func (s *Settings) GetBaseURL() string {
	return s.Proto.BaseUrl.GetValue()
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
	return time.Second * time.Duration(s.Proto.XFileStreamRetryWaitMinSeconds.GetValue())
}

// Final wait in-between filestream retries.
func (s *Settings) GetFileStreamRetryWaitMax() time.Duration {
	return time.Second * time.Duration(s.Proto.XFileStreamRetryWaitMaxSeconds.GetValue())
}

// Per-retry timeout for filestream operations.
func (s *Settings) GetFileStreamTimeout() time.Duration {
	return time.Second * time.Duration(s.Proto.XFileStreamTimeoutSeconds.GetValue())
}

// Interval at which to transmit filestream updates.
func (s *Settings) GetFileStreamTransmitInterval() time.Duration {
	return time.Second * time.Duration(s.Proto.XFileStreamTransmitInterval.GetValue())
}

// Maximum line length for filestream jsonl files, imposed by the back-end.
func (s *Settings) GetFileStreamMaxLineBytes() int32 {
	return s.Proto.XFileStreamMaxLineBytes.GetValue()
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

// Whether to disable SSL verification.
func (s *Settings) IsInsecureDisableSSL() bool {
	return s.Proto.InsecureDisableSsl.GetValue()
}

// Path to the script that created the run, if available.
func (s *Settings) GetProgram() string {
	return s.Proto.Program.GetValue()
}

// The relative path from the root repository directory to the script that
// created the run. If the script is not in the root repository directory,
// this will be the relative path from the current working directory to the
// script.
//
// For example, if the script is /home/user/project/example.py, and the root
// repository directory is /home/user/project, then the relative path is
// example.py.
//
// If couldn't find the relative path, this will be an empty string.
func (s *Settings) GetProgramRelativePath() string {
	return s.Proto.ProgramRelpath.GetValue()
}

// The relative path from the current working directory to the code path.
//
// For example, if the code path is /home/user/project/example.py, and the
// current working directory is /home/user/project, then the code path local
// is example.py.
//
// If couldn't find the relative path, this will be an empty string.
func (s *Settings) GetProgramRelativePathFromCwd() string {
	return s.Proto.XCodePathLocal.GetValue()
}

// The absolute path from the root repository directory to the script that
// created the run. Root repository directory is defined as the directory
// containing the .git directory, if it exists. Otherwise, it's the current
// working directory.
func (s *Settings) GetProgramAbsolutePath() string {
	return s.Proto.ProgramAbspath.GetValue()
}

// The arguments passed to the script that created the run, if available.
func (s *Settings) GetArgs() []string {
	return s.Proto.XArgs.GetValue()
}

// The operating system of the machine running the run.
func (s *Settings) GetOS() string {
	return s.Proto.XOs.GetValue()
}

// The Docker image used to execute the script.
func (s *Settings) GetDockerImageName() string {
	return s.Proto.Docker.GetValue()
}

// The executable used to execute the script.
func (s *Settings) GetExecutable() string {
	return s.Proto.XExecutable.GetValue()
}

// The Python version used to execute the script.
func (s *Settings) GetPython() string {
	return s.Proto.XPython.GetValue()
}

// The Colab URL, if available.
func (s *Settings) GetColabURL() string {
	return s.Proto.ColabUrl.GetValue()
}

// The name of the host processor the run is running on.
func (s *Settings) GetHostProcessorName() string {
	return s.Proto.Host.GetValue()
}

// The W&B user name.
func (s *Settings) GetUserName() string {
	return s.Proto.Username.GetValue()
}

// The W&B email address.
func (s *Settings) GetEmail() string {
	return s.Proto.Email.GetValue()
}

// Specifies the resume behavior for the run. The available options are:
//
// "must": Resumes from an existing run with the same ID. If no such run exists,
// it will result in failure.
//
// "allow": Attempts to resume from an existing run with the same ID. If none is
// found, a new run will be created.
//
// "never": Always starts a new run. If a run with the same ID already exists,
// it will result in failure.
//
// "auto": Automatically resumes from the most recent failed run on the same
// machine.
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

// Whether to create a job artifact for W&B Launch.
func (s *Settings) IsJobCreationDisabled() bool {
	return s.Proto.DisableJobCreation.GetValue() || s.Proto.XDisableMachineInfo.GetValue()
}

// The W&B sweep URL.
func (s *Settings) GetSweepURL() string {
	return s.Proto.SweepUrl.GetValue()
}

// Checks whether console capture is enabled. If it is, stdout and stderr
// will be captured and sent to W&B.
func (s *Settings) IsConsoleCaptureEnabled() bool {
	return s.Proto.Console.GetValue() != "off"
}

// Whether to capture console logs in multipart format.
//
// This is used to make sure we don't overwrite the console log file if it
// already exists.
//
// The format is: logs/output_<optional:Settings.Label>_<timestamp>_<nanoseconds>.log
func (s *Settings) IsConsoleMultipart() bool {
	return s.Proto.ConsoleMultipart.GetValue()
}

// Whether to disable metadata collection.
func (s *Settings) IsDisableMeta() bool {
	return s.Proto.XDisableMeta.GetValue()
}

// Whether to save the code used to create the run.
func (s *Settings) IsSaveCode() bool {
	return s.Proto.SaveCode.GetValue()
}

// Whether to disable git capture and diff generation.
func (s *Settings) IsDisableGit() bool {
	return s.Proto.DisableGit.GetValue()
}

// Whether to disable machine info collection, such as hostname and hardware
// spec.
func (s *Settings) IsDisableMachineInfo() bool {
	return s.Proto.XDisableMachineInfo.GetValue()
}

// Whether to disable system metrics collection.
func (s *Settings) IsDisableStats() bool {
	return s.Proto.XDisableStats.GetValue()
}

func (s *Settings) IsEnableServerSideDerivedSummary() bool {
	return s.Proto.XServerSideDerivedSummary.GetValue()
}

func (s *Settings) IsEnableServerSideExpandGlobMetrics() bool {
	return s.Proto.XServerSideExpandGlobMetrics.GetValue()
}

// Determines whether to save internal wandb files and metadata.
//
// In a distributed setting, this is useful for avoiding file overwrites from secondary processes
// when only system metrics and logs are needed, as the primary process handles the main logging.
func (s *Settings) IsPrimary() bool {
	return s.Proto.XPrimary.GetValue()
}

// The size of the buffer for system metrics.
func (s *Settings) GetStatsBufferSize() int32 {
	return s.Proto.XStatsBufferSize.GetValue()
}

// The sampling interval for system metrics.
func (s *Settings) GetStatsSamplingInterval() float64 {
	return s.Proto.XStatsSamplingInterval.GetValue()
}

// The PID to monitor for system metrics.
func (s *Settings) GetStatsPid() int32 {
	return s.Proto.XStatsPid.GetValue()
}

// The disk paths to monitor for system metrics.
func (s *Settings) GetStatsDiskPaths() []string {
	return s.Proto.XStatsDiskPaths.GetValue()
}

// The indices of GPU devices to monitor.
func (s *Settings) GetStatsGpuDeviceIds() []int32 {
	return s.Proto.XStatsGpuDeviceIds.GetValue()
}

// The path to the Neuron monitor config file.
func (s *Settings) GetStatsNeuronMonitorConfigPath() string {
	return s.Proto.XStatsNeuronMonitorConfigPath.GetValue()
}

// The OpenMetrics API query.
func (s *Settings) GetStatsDcgmExporter() string {
	return s.Proto.XStatsDcgmExporter.GetValue()
}

// The OpenMetrics endpoints to monitor.
func (s *Settings) GetStatsOpenMetricsEndpoints() map[string]string {
	return s.Proto.XStatsOpenMetricsEndpoints.GetValue()
}

// The OpenMetrics filters for the endpoints.
func (s *Settings) GetStatsOpenMetricsFilters() *spb.OpenMetricsFilters {
	return s.Proto.XStatsOpenMetricsFilters
}

// Headers to add to OpenMetrics HTTP requests.
func (s *Settings) GetStatsOpenMetricsHeaders() map[string]string {
	return s.Proto.XStatsOpenMetricsHttpHeaders.GetValue()
}

// The scheme and hostname for contacting the CoreWeave metadata server.
func (s *Settings) GetStatsCoreWeaveMetadataBaseURL() string {
	return s.Proto.XStatsCoreweaveMetadataBaseUrl.GetValue()
}

// The relative path on the CoreWeave metadata server to which to make requests.
func (s *Settings) GetStatsCoreWeaveMetadataEndpoint() string {
	return s.Proto.XStatsCoreweaveMetadataEndpoint.GetValue()
}

// User-provided CPU count to override the auto-detected value in the run metadata.
func (s *Settings) GetStatsCpuCount() int32 {
	return s.Proto.XStatsCpuCount.GetValue()
}

// User-provided Logical CPU count to override the auto-detected value in the run metadata.
func (s *Settings) GetStatsCpuLogicalCount() int32 {
	return s.Proto.XStatsCpuLogicalCount.GetValue()
}

// User-provided GPU count to override the auto-detected value in the run metadata.
func (s *Settings) GetStatsGpuCount() int32 {
	return s.Proto.XStatsGpuCount.GetValue()
}

// User-provided GPU type to override the auto-detected value in the run metadata.
func (s *Settings) GetStatsGpuType() string {
	return s.Proto.XStatsGpuType.GetValue()
}

// Whether to track the process-specific metrics for the entire process tree.
func (s *Settings) GetStatsTrackProcessTree() bool {
	return s.Proto.XStatsTrackProcessTree.GetValue()
}

// The label for the run namespacing for console output and system metrics.
func (s *Settings) GetLabel() string {
	return s.Proto.XLabel.GetValue()
}

// Update methods.
//
// These are used to update the settings in the proto.

// Updates the start time of the run.
func (s *Settings) UpdateStartTime(startTime time.Time) {
	s.Proto.XStartTime = &wrapperspb.DoubleValue{
		Value: float64(startTime.UnixNano()) / 1e9,
	}
}

// Updates the run's entity name.
func (s *Settings) UpdateEntity(entity string) {
	s.Proto.Entity = &wrapperspb.StringValue{Value: entity}
}

// Updates the run's project name.
func (s *Settings) UpdateProject(project string) {
	s.Proto.Project = &wrapperspb.StringValue{Value: project}
}

// Updates the run's display name.
func (s *Settings) UpdateDisplayName(displayName string) {
	s.Proto.RunName = &wrapperspb.StringValue{Value: displayName}
}

// Updates the run ID.
func (s *Settings) UpdateRunID(runID string) {
	s.Proto.RunId = &wrapperspb.StringValue{Value: runID}
}

// Update server-side derived summary computation setting.
func (s *Settings) UpdateServerSideDerivedSummary(enable bool) {
	s.Proto.XServerSideDerivedSummary = &wrapperspb.BoolValue{Value: enable}
}

// Updates the scheme and hostname for contacting the CoreWeave metadata server.
func (s *Settings) UpdateStatsCoreWeaveMetadataBaseURL(baseURL string) {
	s.Proto.XStatsCoreweaveMetadataBaseUrl = &wrapperspb.StringValue{Value: baseURL}
}

// Updates the relative path on the CoreWeave metadata server to which to make requests.
func (s *Settings) UpdateStatsCoreWeaveMetadataEndpoint(endpoint string) {
	s.Proto.XStatsCoreweaveMetadataEndpoint = &wrapperspb.StringValue{Value: endpoint}
}
