using Wandb.Internal;

namespace Wandb
{
    public class Session : IDisposable
    {
        private readonly Manager _manager;
        private bool _isInitialized;
        private int? _port;

        public Session()
        {
            _manager = new Manager();
        }

        public async Task Setup()
        {
            // TODO: move this logic to manager
            if (_isInitialized)
            {
                return;
            }
            // TODO: get timeout from settings
            var timeout = TimeSpan.FromSeconds(30);
            _port = await _manager.LaunchCore(timeout).ConfigureAwait(false);
            _isInitialized = true;
        }

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

        public void Dispose()
        {
            _manager.Dispose();
        }
    }
}
