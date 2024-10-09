using Microsoft.Extensions.Logging;
using Wandb.Internal;
using WandbInternal;

namespace Wandb
{

    /// <summary>
    /// Manages a wandb session, handling initialization and resource cleanup.
    /// </summary>
    public class Session : IDisposable
    {
        private readonly Manager _manager;
        private bool _isInitialized;
        private int? _port;

        public Session()
        {
            _manager = new Manager();
        }

        /// <summary>
        /// Sets up the session by launching the wandb-core process if not already initialized.
        /// </summary>
        /// <param name="timeout">
        /// The timeout in seconds to wait for the core process to start. Defaults to 30 seconds.
        /// </param>
        /// <returns>A task representing the asynchronous operation.</returns>
        public async Task Setup(
            float timeout = 30.0f
        )
        {
            // TODO: move this logic to manager
            if (_isInitialized)
            {
                return;
            }
            _port = await _manager.LaunchCore(TimeSpan.FromSeconds(timeout)).ConfigureAwait(false);
            _isInitialized = true;
        }

        /// <summary>
        /// Initializes a new run within the session.
        /// </summary>
        /// <param name="settings">
        /// Optional settings for the run. If <c>null</c>, default settings are used.
        /// </param>
        /// <returns>
        /// A task representing the asynchronous operation. The task result contains the initialized <see cref="Run"/>.
        /// </returns>
        /// <exception cref="InvalidOperationException">Thrown if the port is not set.</exception>
        public async Task<Run> Init(
            Settings? settings = null,
            ILogger? logger = null
        )
        {
            await Setup().ConfigureAwait(false);

            var _settings = settings ?? new Settings();

            // Create the run directory structure
            Directory.CreateDirectory(_settings.SyncDir);
            Directory.CreateDirectory(_settings.FilesDir);
            Directory.CreateDirectory(_settings.LogDir);


            if (_port == null)
            {
                throw new InvalidOperationException("Port not set");
            }
            var run = new Run(new SocketInterface((int)_port, _settings.RunId), _settings, logger);
            await run.Init().ConfigureAwait(false);

            return run;
        }

        /// <summary>
        /// Checks if the provided API key is valid on the server specified by the base URL.
        ///
        /// TODO: This is an experimental feature and may be removed or changed in the future.
        /// </summary>
        /// <param name="apiKey">
        /// The API key to check. If <c>null</c>, the API key is read from the environment variable
        /// <c>WANDB_API_KEY</c>.
        /// </param>
        /// <param name="baseUrl">
        /// The base URL of the server to check the API key against. If <c>null</c>,
        /// the base URL is read from the environment variable <c>WANDB_BASE_URL</c>.
        /// Defaults to <c>https://api.wandb.ai</c>.
        /// </param>
        /// <returns>Default entity for the API key.</returns>
        /// <exception cref="InvalidOperationException"></exception>
        public async Task<string> Authenticate(string? apiKey = null, string? baseUrl = null)
        {
            // ensure wandb-core is running
            await Setup().ConfigureAwait(false);

            if (_port == null)
            {
                throw new InvalidOperationException("Port not set");
            }
            var randomStringGenerator = new Library.RandomStringGenerator();
            var streamId = randomStringGenerator.GenerateRandomString(8);
            var _interface = new SocketInterface((int)_port, streamId);

            var result = await _interface.Authenticate(
                apiKey ?? Environment.GetEnvironmentVariable("WANDB_API_KEY") ?? throw new InvalidOperationException("API key not set"),
                baseUrl ?? Environment.GetEnvironmentVariable("WANDB_BASE_URL") ?? "https://api.wandb.ai",
                timeoutMilliseconds: 30000 // TODO: get the timeout from settings
            ).ConfigureAwait(false);

            _interface.Dispose();

            return result;
        }

        /// <summary>
        /// Releases all resources used by the <see cref="Session"/> class.
        /// </summary>
        public void Dispose()
        {
            _manager.Dispose();
        }
    }
}
