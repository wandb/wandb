using System.Text.Json;
using WandbInternal;

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

        // GetEnumerator method to allow iteration over the configuration
        public IEnumerator<KeyValuePair<string, object>> GetEnumerator()
        {
            return _configData.GetEnumerator();
        }

        public ConfigRecord ToProto()
        {
            var config = new ConfigRecord();
            foreach (var (key, value) in this)
            {
                config.Update.Add(new ConfigItem
                {
                    Key = key,
                    ValueJson = JsonSerializer.Serialize(value)
                });
            }
            return config;
        }
    }
}
