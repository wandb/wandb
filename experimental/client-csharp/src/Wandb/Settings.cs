namespace Wandb
{
    public class Settings(string baseUrl, string runId)
    {
        readonly string baseUrl = baseUrl;
        readonly string runId = runId;

        public string GetBaseUrl()
        {
            return baseUrl;
        }

        public string GetRunId()
        {
            return runId;
        }
    }
}
