using Wandb.Internal;

namespace Wandb
{
    public class Session : IDisposable
    {
        private readonly Manager _manager;
        private bool _isInitialized = false;
        private int? _port = null;

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
            _port = await _manager.LaunchCore(timeout);
            _isInitialized = true;
        }

        public async Task<Run> Init(
            Settings? settings = null
        )
        {
            await Setup();

            var _settings = settings ?? new Settings();

            // Create the run directory structure
            Directory.CreateDirectory(_settings.SyncDir);
            Directory.CreateDirectory(_settings.FilesDir);
            Directory.CreateDirectory(_settings.LogDir);


            if (_port == null)
            {
                throw new Exception("Port not set");
            }
            var client = new WandbTcpClient();
            client.Connect("localhost", _port.Value);

            var run = new Run(new SocketInterface(client, _settings.RunId), _settings);
            await run.Init();

            return run;
        }

        public void Dispose()
        {
            _manager.Dispose();
        }
    }
}
