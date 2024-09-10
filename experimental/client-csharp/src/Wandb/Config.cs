namespace Wandb
{
    public class Config
    {
        // Event to notify when configuration changes
        public event Action<string, object> ConfigUpdated;

        private Dictionary<string, object> _configData = new Dictionary<string, object>();

        // Indexer to access the configuration as a dictionary-like object
        public object this[string key]
        {
            get => _configData.ContainsKey(key) ? _configData[key] : null;
            set
            {
                _configData[key] = value;
                // Trigger the event callback when updated
                ConfigUpdated?.Invoke(key, value);
            }
        }
    }
}
