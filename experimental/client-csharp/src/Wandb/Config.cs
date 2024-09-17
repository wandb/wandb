using System.Text.Json;
using WandbInternal;

namespace Wandb
{
    /// <summary>
    /// Represents a dynamic configuration that allows for setting and retrieving key-value pairs.
    /// </summary>
    public class Config
    {
        /// <summary>
        /// Occurs when a configuration item is updated.
        /// </summary>
        public event Action<string, object> ConfigUpdated;

        private Dictionary<string, object> _configData = new Dictionary<string, object>();

        /// <summary>
        /// Gets or sets the configuration value associated with the specified key.
        /// </summary>
        /// <param name="key">The key of the configuration item.</param>
        /// <returns>
        /// The value associated with the specified key, or <c>null</c> if the key does not exist.
        /// </returns>
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

        /// <summary>
        /// Returns an enumerator that iterates through the configuration items.
        /// </summary>
        /// <returns>
        /// An enumerator for the configuration dictionary.
        /// </returns>
        public IEnumerator<KeyValuePair<string, object>> GetEnumerator()
        {
            return _configData.GetEnumerator();
        }

        /// <summary>
        /// Converts the configuration data to a protocol buffer record.
        /// </summary>
        /// <returns>
        /// A <see cref="ConfigRecord"/> representing the current configuration.
        /// </returns>
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
