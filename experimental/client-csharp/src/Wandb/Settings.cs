namespace Wandb
{
    public class Settings(string runId)
    {
        readonly string runId = runId;

        public string GetRunId()
        {
            return runId;
        }
    }
}
