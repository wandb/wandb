using System.Text.Json;
using WandbInternal;
using Wandb.Internal;

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
        /// The configuration for the run.
        /// </summary>
        public Config Config { get; private set; }

        /// <summary>
        /// The internal step at which the run starts.
        /// Used when resuming a run.
        /// </summary>
        public int StartingStep { get; private set; }

        /// <summary>
        /// Initializes a new instance of the <see cref="Run"/> class.
        /// </summary>
        /// <param name="interface">The socket interface for communication.</param>
        /// <param name="settings">The settings for the run.</param>
        internal Run(SocketInterface @interface, Settings settings)
        {
            _interface = @interface;

            Settings = settings;

            Config = new Config();
            // Subscribe to ConfigUpdated event
            Config.ConfigUpdated += OnConfigUpdated;
        }

        /// <summary>
        /// Callback method invoked when the configuration is updated.
        /// </summary>
        /// <param name="key">The key of the configuration item.</param>
        /// <param name="value">The new value of the configuration item.</param>
        private async void OnConfigUpdated(string key, object value)
        {
            // Handle the updated configuration
            await _interface.PublishConfig(key, value).ConfigureAwait(false); // Example method in SocketInterface
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

            // save project, entity, display name, and resume status to settings
            Settings.Project = runResult.Run.Project;
            Settings.Entity = runResult.Run.Entity;
            Settings.DisplayName = runResult.Run.DisplayName;
            Settings.Resumed = runResult.Run.Resumed;

            StartingStep = (int)runResult.Run.StartingStep;

            // TODO: save config to the run for local access
            // Console.WriteLine(runResult.Run.Config);

            Result result = await _interface.DeliverRunStart(this, 30000).ConfigureAwait(false);

            if (result.Response == null)
            {
                throw new Exception("Failed to deliver run start");
            }

            // TODO: update the config

            PrintRunURL();
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
            string stepMetric,
            SummaryType? summary = null,
            bool? hidden = false
        )
        {
            await _interface.PublishMetricDefinition(name, stepMetric, summary, hidden).ConfigureAwait(false);
        }

        /// <summary>
        /// Completes the run by sending exit commands and cleaning up resources.
        /// </summary>
        /// <returns>A task that represents the asynchronous operation.</returns>
        /// <exception cref="Exception">Thrown when the exit delivery fails.</exception>
        public async Task Finish()
        {
            // TODO: get timeout from settings
            Result deliverExitResult = await _interface.DelieverExit(timeoutMilliseconds: 600000).ConfigureAwait(false);
            if (deliverExitResult.ExitResult == null)
            {
                throw new Exception("Failed to deliver exit");
            }
            // Send finish command
            await _interface.InformFinish().ConfigureAwait(false);
            PrintRunURL();
            PrintRunDir();
        }

        /// <summary>
        /// Prints the URL of the run to the console.
        /// </summary>
        private void PrintRunURL()
        {
            // Set the color for the prefix to blue
            Console.ForegroundColor = ConsoleColor.Blue;
            Console.Write("wandb");

            // Reset the color and write the remaining text on the same line
            Console.ResetColor();
            Console.Write(": View run ");

            // Set the color for the display name to yellow
            Console.ForegroundColor = ConsoleColor.Yellow;
            Console.Write(Settings.DisplayName);

            // Reset the color and write " at "
            Console.ResetColor();
            Console.Write(" at ");

            // Set the color for the URL to magenta
            Console.Write("\u001b[4m");  // Enable underline
            Console.ForegroundColor = ConsoleColor.DarkBlue;
            Console.Write(Settings.RunURL);
            Console.Write("\u001b[0m");  // Reset formatting

            // Reset the color back to default
            Console.ResetColor();

            // End the line
            Console.WriteLine();
        }

        /// <summary>
        /// Prints the directory where run data is saved locally.
        /// </summary>
        private void PrintRunDir()
        {
            // Set the color for the prefix to blue
            Console.ForegroundColor = ConsoleColor.Blue;
            Console.Write("wandb");

            // Reset the color and write the remaining text on the same line
            Console.ResetColor();
            Console.Write(": Run data is saved locally in ");

            // Set the color for the URL to magenta
            Console.ForegroundColor = ConsoleColor.Magenta;
            Console.Write(Settings.SyncDir);

            // Reset the color back to default
            Console.ResetColor();

            // End the line
            Console.WriteLine();
        }

        /// <summary>
        /// Releases all resources used by the <see cref="Run"/> class.
        /// </summary>
        public void Dispose()
        {
            _interface.Dispose();
            // Unsubscribe to avoid memory leaks
            Config.ConfigUpdated -= OnConfigUpdated;
        }
    }
}
