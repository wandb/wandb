namespace Wandb
{
    public class Settings
    {
        public string BaseUrl { get; }
        public string Mode { get; }
        public string RunId { get; }
        public string Timespec { get; }
        public string Project { get; private set; }

        public Settings(
            string runId,
            string timespec,
            string baseUrl = "https://api.wandb.ai",
            string mode = "online",
            string project = "uncategorized"
            )
        {
            RunId = runId;
            Timespec = timespec;
            BaseUrl = baseUrl;
            Mode = mode;
            Project = project;
        }

        public string FilesDir => Path.Combine(SyncDir, "files");
        public string LogDir => Path.Combine(SyncDir, "logs");
        public string LogInternal => Path.Combine(LogDir, "debug-internal.log");
        public static string LogSymlinkInternal => Path.Combine(WandbDir, "debug-internal.log");
        public static string LogSymlinkUser => Path.Combine(WandbDir, "debug.log");
        public string LogUser => Path.Combine(LogDir, "debug.log");
        public bool IsOffline => Mode == "offline";
        public string RunMode => Mode == "offline" ? "offline-run" : "run";
        public string SyncDir => Path.Combine(WandbDir, $"{RunMode}-{Timespec}-{RunId}");
        public string SyncFile => Path.Combine(SyncDir, $"run-{RunId}.wandb");

        public static string WandbDir => Path.Combine(Environment.CurrentDirectory, ".wandb");

        public void SetProject(string project)
        {
            Project = project;
        }

        public WandbInternal.Settings ToProto()
        {
            return new WandbInternal.Settings
            {
                BaseUrl = BaseUrl,
                FilesDir = FilesDir,
                LogDir = LogDir,
                LogInternal = LogInternal,
                LogSymlinkInternal = LogSymlinkInternal,
                LogSymlinkUser = LogSymlinkUser,
                LogUser = LogUser,
                Mode = Mode,
                Offline = IsOffline,
                RunId = RunId,
                RunMode = RunMode,
                SyncDir = SyncDir,
                SyncFile = SyncFile,
                Timespec = Timespec,
                WandbDir = WandbDir
            };
        }
    }
}
