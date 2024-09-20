using Wandb.Internal;

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
            Settings? settings = null
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
            var run = new Run(new SocketInterface((int)_port, _settings.RunId), _settings);
            await run.Init().ConfigureAwait(false);

            return run;
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
