using System.Text;

namespace Wandb
{
    /// <summary>
    /// Specifies options for resuming a run.
    /// See https://docs.wandb.ai/guides/runs/resuming for more information.
    /// </summary>
    public enum ResumeOption
    {
        /// <summary>
        /// wandb must resume run specified by the run ID.
        /// If the run does not exist, an error is thrown.
        /// </summary>
        Must,

        /// <summary>
        /// Allow wandb to resume run if run ID exists.
        /// If the run does not exist, a new run is created.
        /// </summary>
        Allow,

        /// <summary>
        /// Never allow wandb to resume a run specified by run ID.
        /// If the run exists, an error is thrown.
        /// </summary>
        Never
    }

    /// <summary>
    /// Represents the settings for a wandb run.
    /// </summary>
    public class Settings
    {
        /// <summary>
        /// Gets or sets the API key used for authentication.
        /// </summary>
        public string ApiKey { get; set; }

        /// <summary>
        /// Gets the base URL of the wandb server.
        /// </summary>
        public string BaseUrl { get; }

        /// <summary>
        /// Gets or sets the display name of the run.
        /// </summary>
        public string DisplayName { get; set; }

        /// <summary>
        /// Gets or sets the entity (user or team) under which the run is logged.
        /// </summary>
        public string Entity { get; set; }

        /// <summary>
        /// Gets the mode in which the run operates (e.g., "online" or "offline").
        /// </summary>
        public string Mode { get; }

        /// <summary>
        /// Gets or sets the project name under which the run is logged.
        /// </summary>
        public string Project { get; set; }

        /// <summary>
        /// Gets or sets the resume option for the run.
        /// </summary>
        public ResumeOption? Resume { get; set; }

        /// <summary>
        /// Gets or sets a value indicating whether the run has resumed from a previous state.
        /// </summary>
        public bool Resumed { get; set; }

        /// <summary>
        /// Gets the unique identifier for the run.
        /// </summary>
        public string RunId { get; }

        /// <summary>
        /// Gets or sets the amount of time (in seconds) to wait for wandb-core to launch.
        /// </summary>
        public float ServiceWait { get; set; }

        /// <summary>
        /// Gets or sets the run initialization timeout (in seconds).
        /// </summary>
        public float InitTimeout { get; set; }

        /// <summary>
        /// Gets or sets the start date and time of the run.
        /// </summary>
        public DateTime StartDatetime { get; set; }

        /// <summary>
        /// Converts the <see cref="Resume"/> option to its string representation.
        /// </summary>
        /// <returns>
        /// A lowercase string of the resume option, or <c>null</c> if not set.
        /// </returns>
        public string ResumeOptionToString()
        {
            if (!Resume.HasValue)
            {
                return null;
            }
            else
            {
                return Resume.Value.ToString().ToLowerInvariant();
            }
        }

        /// <summary>
        /// Initializes a new instance of the <see cref="Settings"/> class with optional parameters.
        /// </summary>
        /// <param name="apiKey">The API key for authentication.</param>
        /// <param name="baseUrl">The base URL of the wandb server.</param>
        /// <param name="displayName">The display name of the run.</param>
        /// <param name="entity">The entity under which the run is logged.</param>
        /// <param name="mode">The mode in which the run operates.</param>
        /// <param name="project">The project name.</param>
        /// <param name="resume">The resume option.</param>
        /// <param name="runId">The unique identifier for the run.</param>
        /// <param name="serviceWait">The service wait time in seconds.</param>
        /// <param name="initTimeout">The initialization timeout in seconds.</param>
        public Settings(
            string? apiKey = null,
            string? baseUrl = null,
            string? displayName = null,
            string? entity = null,
            string? mode = null,
            string? project = null,
            ResumeOption? resume = null,
            string? runId = null,
            float serviceWait = 30.0f,
            float initTimeout = 90.0f
            )
        {
            Lib.RandomStringGenerator generator = new();

            ApiKey = apiKey ?? Environment.GetEnvironmentVariable("WANDB_API_KEY") ?? "";
            BaseUrl = baseUrl ?? Environment.GetEnvironmentVariable("WANDB_BASE_URL") ?? "https://api.wandb.ai";
            DisplayName = displayName ?? "";
            Entity = entity ?? "";
            Mode = mode ?? "online";
            Project = project ?? Environment.GetEnvironmentVariable("WANDB_PROJECT") ?? "uncategorized";
            Resume = resume;
            RunId = runId ?? Environment.GetEnvironmentVariable("WANDB_RUN_ID") ?? generator.GenerateRandomString(8);
            ServiceWait = serviceWait;
            InitTimeout = initTimeout;

            StartDatetime = DateTime.UtcNow;
        }

        /// <summary>
        /// Gets the timestamp in "yyyyMMdd_HHmmss" format.
        /// </summary>
        public string Timespec => StartDatetime.ToString("yyyyMMdd_HHmmss", System.Globalization.CultureInfo.InvariantCulture);

        /// <summary>
        /// Gets the path to the directory where run files are stored.
        /// </summary>
        public string FilesDir => Path.Combine(SyncDir, "files");

        /// <summary>
        /// Gets the path to the directory where run logs are stored.
        /// </summary>
        public string LogDir => Path.Combine(SyncDir, "logs");

        /// <summary>
        /// Gets the path to the internal debug log file.
        /// </summary>
        public string LogInternal => Path.Combine(LogDir, "debug-internal.log");

        /// <summary>
        /// Gets the symlink path for the internal debug log.
        /// </summary>
        public static string LogSymlinkInternal => Path.Combine(WandbDir, "debug-internal.log");

        /// <summary>
        /// Gets the symlink path for the user process debug log.
        /// </summary>
        public static string LogSymlinkUser => Path.Combine(WandbDir, "debug.log");

        /// <summary>
        /// Gets the path to the user debug log file.
        /// </summary>
        public string LogUser => Path.Combine(LogDir, "debug.log");

        /// <summary>
        /// Gets a value indicating whether the run is in offline mode.
        /// </summary>
        public bool IsOffline => Mode == "offline";

        /// <summary>
        /// Gets the run mode string based on the current mode.
        /// </summary>
        public string RunMode => Mode == "offline" ? "offline-run" : "run";

        /// <summary>
        /// Gets the URL of the run on the wandb server.
        /// </summary>
        public string RunURL => $"{BaseUrl.Replace("api.wandb.ai", "wandb.ai")}/{Entity}/{Project}/runs/{RunId}";

        /// <summary>
        /// Gets the path to the run synchronization directory.
        /// </summary>
        public string SyncDir => Path.Combine(WandbDir, $"{RunMode}-{Timespec}-{RunId}");

        /// <summary>
        /// Gets the path to the run synchronization file.
        /// This file is an append-only log of events that occur during the run.
        /// Can be used to sync run data to the wandb server.
        /// </summary>
        public string SyncFile => Path.Combine(SyncDir, $"run-{RunId}.wandb");

        /// <summary>
        /// Gets the path to the wandb directory.
        /// </summary>
        public static string WandbDir => Path.Combine(Environment.CurrentDirectory, ".wandb");

        /// <summary>
        /// Converts the current settings to a protocol buffer representation.
        /// </summary>
        /// <returns>A <see cref="WandbInternal.Settings"/> object.</returns>
        public WandbInternal.Settings ToProto()
        {
            return new WandbInternal.Settings
            {
                ApiKey = ApiKey,
                BaseUrl = BaseUrl.ToString(),
                Entity = Entity,
                FilesDir = FilesDir,
                InitTimeout = InitTimeout,
                LogDir = LogDir,
                LogInternal = LogInternal,
                LogSymlinkInternal = LogSymlinkInternal,
                LogSymlinkUser = LogSymlinkUser,
                LogUser = LogUser,
                Mode = Mode,
                Offline = IsOffline,
                Project = Project,
                Resume = ResumeOptionToString(),
                Resumed = Resumed,
                RunId = RunId,
                RunMode = RunMode,
                RunName = DisplayName,
                ServiceWait = ServiceWait,
                SyncDir = SyncDir,
                SyncFile = SyncFile,
                Timespec = Timespec,
                WandbDir = WandbDir,
                // TODO: we do not capture extra info by default, but
                // we could make this configurable in the future
                DisableStats = true,
                DisableGit = true,
                DisableMeta = true,
                DisableCode = true,
                DisableJobCreation = true,
                SaveCode = false,
                Console = "off",
                SaveRequirements = false,
            };
        }

        /// <summary>
        /// Returns a string that represents the current settings.
        /// </summary>
        /// <returns>A formatted string containing key settings information.</returns>
        public override string ToString()
        {
            var sb = new StringBuilder();
            sb.AppendLine("Wandb Settings:");
            sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"  Entity: {Entity ?? "Not set"}");
            sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"  Run ID: {RunId}");
            sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"  Display Name: {DisplayName ?? "Not set"}");
            sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"  Timespec: {Timespec}");
            sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"  Base URL: {BaseUrl}");
            sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"  Mode: {Mode}");
            sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"  Project: {Project ?? "Not set"}");
            sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"  Is Offline: {IsOffline}");
            sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"  Run Mode: {RunMode}");
            sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"  Resume: {ResumeOptionToString() ?? "Not set"}");
            sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"  Resumed: {Resumed}");
            // TODO: these make it look like there's an error lol
            // sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"  Wandb Dir: {WandbDir}");
            // sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"  Sync Dir: {SyncDir}");
            // sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"  Files Dir: {FilesDir}");
            // sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"  Log Dir: {LogDir}");
            // sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"  Sync File: {SyncFile}");
            // sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"  Log Internal: {LogInternal}");
            // sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"  Log User: {LogUser}");
            // sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"  Log Symlink Internal: {LogSymlinkInternal}");
            // sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"  Log Symlink User: {LogSymlinkUser}");
            return sb.ToString();
        }
    }
}
