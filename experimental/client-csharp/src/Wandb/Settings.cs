using System.IO;


namespace Wandb
{
    public class Settings(
        string runId,
        string timespec,
        string baseUrl = "https://api.wandb.ai",
        string mode = "online"
        )
    {
        readonly string baseUrl = baseUrl;
        readonly string mode = mode;
        readonly string runId = runId;
        readonly string timespec = timespec;

        public string GetBaseUrl()
        {
            return baseUrl;
        }

        public string GetFilesDir()
        {
            return Path.Combine(GetSyncDir(), "files");
        }

        public string GetLogDir()
        {
            return Path.Combine(GetSyncDir(), "logs");
        }

        public string GetLogInternal()
        {
            return Path.Combine(GetLogDir(), "debug-internal.log");
        }

        public string GetLogSymlinkInternal()
        {
            return Path.Combine(GetWandbDir(), "debug-internal.log");
        }

        public string GetLogSymlinkUser()
        {
            return Path.Combine(GetWandbDir(), "debug.log");
        }

        public string GetLogUser()
        {
            return Path.Combine(GetLogDir(), "debug.log");
        }

        public string GetMode()
        {
            return mode;
        }

        public bool GetOffline()
        {
            return mode == "offline";
        }

        public string GetRunId()
        {
            return runId;
        }

        public string GetRunMode()
        {
            if (mode == "offline")
            {
                return "offline-run";
            }
            return "run";
        }

        public string GetSyncDir()
        {
            return Path.Combine(GetWandbDir(), $"{GetRunMode()}-{timespec}-{runId}");
        }

        public string GetSyncFile()
        {
            return Path.Combine(GetSyncDir(), $"run-{runId}.wandb");
        }

        public string GetTimespec()
        {
            return timespec;
        }

        public static string GetWandbDir()
        {
            // TODO: make this configurable
            return Path.Combine(Environment.CurrentDirectory, ".wandb");
        }

        public WandbInternal.Settings ToProto()
        {
            return new WandbInternal.Settings
            {
                BaseUrl = baseUrl,
                FilesDir = GetFilesDir(),
                LogDir = GetLogDir(),
                LogInternal = GetLogInternal(),
                LogSymlinkInternal = GetLogSymlinkInternal(),
                LogSymlinkUser = GetLogSymlinkUser(),
                LogUser = GetLogUser(),
                Mode = mode,
                Offline = GetOffline(),
                RunId = runId,
                RunMode = GetRunMode(),
                SyncDir = GetSyncDir(),
                SyncFile = GetSyncFile(),
                Timespec = timespec,
                WandbDir = GetWandbDir()
            };
        }
    }
}
