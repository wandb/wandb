using Microsoft.Extensions.Logging;
using Wandb.Internal;

namespace Wandb
{

    /// <summary>
    /// Manages a wandb session, handling initialization and resource cleanup.
    /// </summary>
    public class Session : IDisposable
    {
        private readonly Manager _manager;
        private IServiceConnectionProtocol? _connectionProtocol;

        public Session()
        {
            _manager = new Manager();
        }

        /// <summary>
        /// Launches wandb-core if it hasn't been launched.
        /// </summary>
        /// <param name="timeout">
        /// The timeout in seconds to wait for the core process to start.
        /// </param>
        /// <returns>A way to connect to the service.</returns>
        public async Task<IServiceConnectionProtocol> Setup(float timeout = 30.0f)
        {
            // TODO: move this logic to manager
            if (_connectionProtocol != null)
                return _connectionProtocol;

            _connectionProtocol = await _manager.LaunchCore(
                TimeSpan.FromSeconds(timeout)
            ).ConfigureAwait(false);

            return _connectionProtocol;
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
        /// <exception cref="InvalidOperationException">
        /// Thrown if the connection protocol is not set.
        /// </exception>
        public async Task<Run> Init(
            Settings? settings = null,
            ILogger? logger = null
        )
        {
            var connectionProtocol = await Setup().ConfigureAwait(false);

            var _settings = settings ?? new Settings();

            // Create the run directory structure
            Directory.CreateDirectory(_settings.SyncDir);
            Directory.CreateDirectory(_settings.FilesDir);
            Directory.CreateDirectory(_settings.LogDir);
            var run = new Run(
                new SocketInterface(connectionProtocol, _settings.RunId),
                _settings,
                logger
            );
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
            var connectionProtocol = await Setup().ConfigureAwait(false);

            var randomStringGenerator = new Library.RandomStringGenerator();
            var streamId = randomStringGenerator.GenerateRandomString(8);
            var _interface = new SocketInterface(connectionProtocol, streamId);

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
