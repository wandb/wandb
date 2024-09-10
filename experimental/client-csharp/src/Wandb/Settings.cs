using System.Text;

namespace Wandb
{
    public class Settings
    {
        public string BaseUrl { get; }
        public string DisplayName { get; set; }
        public string Entity { get; set; }
        public string Mode { get; }
        public string Project { get; set; }
        public string RunId { get; }

        public string Timespec { get; }


        public Settings(
            string? baseUrl = null,
            string? displayName = null,
            string? entity = null,
            string? mode = null,
            string? project = null,
            string? runId = null,
            string? timespec = null
            )
        {
            RandomStringGenerator generator = new();

            BaseUrl = baseUrl ?? "https://api.wandb.ai";
            DisplayName = displayName ?? "";
            Entity = entity ?? "";
            Mode = mode ?? "online";
            Project = project ?? "uncategorized";
            RunId = runId ?? generator.GenerateRandomString(8);
            Timespec = timespec ?? DateTime.Now.ToString("yyyyMMdd_HHmmss");
        }

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
                BaseUrl = BaseUrl,
                Entity = Entity,
                FilesDir = FilesDir,
                LogDir = LogDir,
                LogInternal = LogInternal,
                LogSymlinkInternal = LogSymlinkInternal,
                LogSymlinkUser = LogSymlinkUser,
                LogUser = LogUser,
                Mode = Mode,
                Offline = IsOffline,
                Project = Project,
                RunId = RunId,
                RunMode = RunMode,
                RunName = DisplayName,
                SyncDir = SyncDir,
                SyncFile = SyncFile,
                Timespec = Timespec,
                WandbDir = WandbDir
            };
        }

        public override string ToString()
        {
            var sb = new StringBuilder();
            sb.AppendLine("Wandb Settings:");
            sb.AppendLine($"  Entity: {Entity ?? "Not set"}");
            sb.AppendLine($"  Run ID: {RunId}");
            sb.AppendLine($"  Display Name: {DisplayName ?? "Not set"}");
            sb.AppendLine($"  Timespec: {Timespec}");
            sb.AppendLine($"  Base URL: {BaseUrl}");
            sb.AppendLine($"  Mode: {Mode}");
            sb.AppendLine($"  Project: {Project ?? "Not set"}");
            sb.AppendLine($"  Is Offline: {IsOffline}");
            sb.AppendLine($"  Run Mode: {RunMode}");
            // TODO: these make it look like there's an error lol
            // sb.AppendLine($"  Wandb Dir: {WandbDir}");
            // sb.AppendLine($"  Sync Dir: {SyncDir}");
            // sb.AppendLine($"  Files Dir: {FilesDir}");
            // sb.AppendLine($"  Log Dir: {LogDir}");
            // sb.AppendLine($"  Sync File: {SyncFile}");
            // sb.AppendLine($"  Log Internal: {LogInternal}");
            // sb.AppendLine($"  Log User: {LogUser}");
            // sb.AppendLine($"  Log Symlink Internal: {LogSymlinkInternal}");
            // sb.AppendLine($"  Log Symlink User: {LogSymlinkUser}");
            return sb.ToString();
        }
    }
}
