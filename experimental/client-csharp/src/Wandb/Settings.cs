using System.Text;


namespace Wandb
{
    public enum ResumeOption
    {
        Must,
        Allow,
        Never
    }

    public class Settings
    {
        public string ApiKey { get; set; }
        public string BaseUrl { get; }
        public string DisplayName { get; set; }
        public string Entity { get; set; }
        public string Mode { get; }
        public string Project { get; set; }
        public ResumeOption? Resume { get; set; }
        public bool Resumed { get; set; }
        public string RunId { get; }
        public float ServiceWait { get; set; }
        public float InitTimeout { get; set; }

        public DateTime StartDatetime { get; set; }

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
            RunId = runId ?? generator.GenerateRandomString(8);
            ServiceWait = serviceWait;
            InitTimeout = initTimeout;

            StartDatetime = DateTime.UtcNow;
        }

        public string Timespec => StartDatetime.ToString("yyyyMMdd_HHmmss", System.Globalization.CultureInfo.InvariantCulture);
        public string FilesDir => Path.Combine(SyncDir, "files");
        public string LogDir => Path.Combine(SyncDir, "logs");
        public string LogInternal => Path.Combine(LogDir, "debug-internal.log");
        public static string LogSymlinkInternal => Path.Combine(WandbDir, "debug-internal.log");
        public static string LogSymlinkUser => Path.Combine(WandbDir, "debug.log");
        public string LogUser => Path.Combine(LogDir, "debug.log");
        public bool IsOffline => Mode == "offline";
        public string RunMode => Mode == "offline" ? "offline-run" : "run";

        public string RunURL => $"{BaseUrl.Replace("api.wandb.ai", "wandb.ai")}/{Entity}/{Project}/runs/{RunId}";
        public string SyncDir => Path.Combine(WandbDir, $"{RunMode}-{Timespec}-{RunId}");
        public string SyncFile => Path.Combine(SyncDir, $"run-{RunId}.wandb");

        public static string WandbDir => Path.Combine(Environment.CurrentDirectory, ".wandb");

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
