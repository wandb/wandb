using Serilog;
using WandbInternal;
using Wandb.Internal;
using Newtonsoft.Json;

namespace Wandb
{
    /// <summary>
    /// Specifies the type of summary statistics to compute for metrics.
    /// </summary>
    [Flags]
    public enum SummaryType
    {
        /// <summary>
        /// No summary statistics.
        /// </summary>
        None = 0,
        /// <summary>
        /// Compute the minimum value.
        /// </summary>
        Min = 1 << 0,   // 1
        /// <summary>
        /// Compute the maximum value.
        /// </summary>
        Max = 1 << 1,   // 2
        /// <summary>
        /// Compute the mean value.
        /// </summary>
        Mean = 1 << 2,  // 4
        /// <summary>
        /// Use the last value.
        /// </summary>
        Last = 1 << 3,  // 8
    }

    /// <summary>
    /// Represents a wandb run and provides methods to interact with it.
    /// For more information on wandb runs, see https://docs.wandb.ai/guides/runs.
    /// </summary>
    public class Run : IDisposable
    {
        private readonly SocketInterface _interface;

        /// <summary>
        /// The settings for the run.
        /// </summary>
        public Settings Settings { get; private set; }

        /// <summary>
        /// The internal step at which the run starts.
        /// Used when resuming a run.
        /// </summary>
        public int StartingStep { get; private set; }

        /// <summary>
        ///  The logger for the run.
        /// </summary>
        private readonly ILogger _logger;

        /// <summary>
        /// Initializes a new instance of the <see cref="Run"/> class.
        /// </summary>
        /// <param name="interface">The socket interface for communication.</param>
        /// <param name="settings">The settings for the run.</param>
        internal Run(SocketInterface @interface, Settings settings, ILogger? logger = null)
        {
            _interface = @interface;

            Settings = settings;

            _logger = logger ?? new LoggerConfiguration()
            .MinimumLevel.Debug()
            .Enrich.WithProperty("Source", "wandb")
            .WriteTo.File(
                settings.LogUser,
                outputTemplate: "{Timestamp:yyyy-MM-dd HH:mm:ss.fff zzz} [{Level:u3}] {Source}: {Message:lj}{NewLine}{Exception}"
            )
            .CreateLogger();
            _logger.Information("Run created");
        }

        /// <summary>
        /// Updates the configuration of the run.
        /// </summary>
        /// <param name="update">A dictionary containing the updated configuration.</param>
        public async Task UpdateConfig(Dictionary<string, object> update)
        {
            // Handle the updated configuration
            await _interface.PublishConfig(update).ConfigureAwait(false);
        }

        /// <summary>
        /// Initializes the run by communicating with wandb-core and setting up necessary configurations.
        /// </summary>
        /// <returns>A task that represents the asynchronous operation.</returns>
        /// <exception cref="Exception">Thrown when the run initialization fails.</exception>
        public async Task Init()
        {
            await _interface.InformInit(Settings).ConfigureAwait(false);
            var initTimeoutMs = (int)(Settings.InitTimeout * 1000);
            Result deliverRunResult = await _interface.DeliverRun(this, initTimeoutMs).ConfigureAwait(false);
            if (deliverRunResult.RunResult == null)
            {
                throw new Exception("Failed to deliver run");
            }

            RunUpdateResult runResult = deliverRunResult.RunResult;
            if (runResult.Error != null)
            {
                throw new Exception(runResult.Error.Message);
            }

            if (runResult.Run.Summary != null)
            {
                await _interface.PublishSummary(runResult.Run.Summary).ConfigureAwait(false);
            }

            // save project, entity, display name, and resume status to settings
            Settings.Project = runResult.Run.Project;
            Settings.Entity = runResult.Run.Entity;
            Settings.DisplayName = runResult.Run.DisplayName;
            Settings.Resumed = runResult.Run.Resumed;

            StartingStep = (int)runResult.Run.StartingStep;

            Result result = await _interface.DeliverRunStart(this, 30000).ConfigureAwait(false);

            if (result.Response == null)
            {
                throw new Exception("Failed to deliver run start");
            }

            _logger.Information("View run {DisplayName} at {RunURL}", Settings.DisplayName, Settings.RunURL);
        }

        /// <summary>
        /// Logs data to the run.
        /// </summary>
        /// <param name="data">A dictionary containing the data to log.</param>
        /// <returns>A task that represents the asynchronous operation.</returns>
        public async Task Log(Dictionary<string, object> data)
        {
            await _interface.PublishPartialHistory(data).ConfigureAwait(false);
        }

        /// <summary>
        /// Customize metrics logged with Log.
        /// </summary>
        /// <param name="name">The name of the metric to customize.</param>
        /// <param name="stepMetric">The name of another metric to serve as the X-axis
        /// for this metric in automatically generated charts.</param>
        /// <param name="summary">The type of summary statistics to compute for the metric.</param>
        /// <param name="hidden">Hide this metric from automatic plots.</param>
        /// <returns>A task that represents the asynchronous operation.</returns>
        public async Task DefineMetric(
            string name,
            string? stepMetric = null,
            SummaryType? summary = null,
            bool? hidden = false
        )
        {
            await _interface.PublishMetricDefinition(name, stepMetric, summary, hidden).ConfigureAwait(false);
        }

        /// <summary>
        /// Gets the run's summary.
        /// </summary>
        /// <returns></returns>
        public async Task<T> GetSummary<T>() where T : new()
        {
            var timeoutMs = 20000;  // TODO: make this configurable
            var result = await _interface.DeliverGetSummary(timeoutMs).ConfigureAwait(false);

            var summary = new Dictionary<string, object>();
            // iterate over the summary and print the key-value pairs
            foreach (var item in result.Response.GetSummaryResponse.Item)
            {
                string key = item.Key;
                // skip internal keys
                if (key == "_wandb" || key == "_runtime" || key == "_step")
                {
                    continue;
                }

                string valueJson = item.ValueJson;

                try
                {
                    var deserializedValue = JsonConvert.DeserializeObject<T>(valueJson);
                    if (deserializedValue != null)
                    {
                        summary[key] = deserializedValue;
                    }
                    else
                    {
                        // If the value doesn't match the type, just store the raw JSON
                        summary[key] = JsonConvert.DeserializeObject<object>(valueJson);
                    }
                }
                catch (JsonSerializationException)
                {
                    // If the deserialization to T fails, just store it as a dynamic object
                    summary[key] = JsonConvert.DeserializeObject<object>(valueJson);
                }
            }

            // Serialize the summary to JSON and then deserialize it to the specified type
            var jsonSummary = JsonConvert.SerializeObject(summary);
            T typedSummary = JsonConvert.DeserializeObject<T>(jsonSummary);
            return typedSummary;
        }

        /// <summary>
        /// Completes the run by sending exit commands and cleaning up resources.
        /// </summary>
        /// <param name="markFinished">Whether to mark the run as finished on the server.</param>
        /// <returns>A task that represents the asynchronous operation.</returns>
        /// <exception cref="Exception">Thrown when the exit delivery fails.</exception>
        public async Task Finish(bool markFinished = true)
        {
            // TODO: get timeout from settings
            if (markFinished)
            {
                Result deliverExitResult = await _interface.DeliverExit(timeoutMilliseconds: 600000).ConfigureAwait(false);
                if (deliverExitResult.ExitResult == null)
                {
                    throw new Exception("Failed to deliver exit");
                }
            }
            else
            {
                Result deliverFinishWithoutExitResult = await _interface.DeliverFinishWithoutExit(timeoutMilliseconds: 600000).ConfigureAwait(false);
                if (deliverFinishWithoutExitResult.Response.RunFinishWithoutExitResponse == null)
                {
                    throw new Exception("Failed to deliver finish without exit");
                }
            }

            // Send finish command
            await _interface.InformFinish().ConfigureAwait(false);

            _logger.Information("Run {DisplayName} data is saved locally in {SyncDir}", Settings.DisplayName, Settings.SyncDir);
            _logger.Information("Run {DisplayName} finished", Settings.DisplayName);
        }

        /// <summary>
        /// Releases all resources used by the <see cref="Run"/> class.
        /// </summary>
        public void Dispose()
        {
            _interface.Dispose();

            // Ensure all log entries are flushed before disposing the session
            if (_logger is Serilog.Core.Logger logger)
            {
                logger.Dispose();  // Flushes and disposes the logger if it's the Serilog implementation
            }
        }
    }
}
