using Wandb.Internal;

namespace Wandb
{
    public class Session : IDisposable
    {
        private readonly Manager _manager;
        private readonly TcpCommunication _tcpCommunication;
        private bool _isInitialized = false;
        private int? _port = null;

        public Session()
        {
            _manager = new Manager();
            _tcpCommunication = new TcpCommunication();
        }

        public async Task Setup()
        {

            if (!_isInitialized)
            {
                var timeout = TimeSpan.FromSeconds(30); // TODO: get from default settings
                _port = await _manager.LaunchCore(timeout);
                await _tcpCommunication.Open(_port.Value);
                _isInitialized = true;
            }
        }

        public async Task<Run> Init(
            string? project = null
        )
        {
            await Setup();

            var settings = new Settings(
                project: project
            );

            // Create the run directory structure
            Directory.CreateDirectory(settings.SyncDir);
            Directory.CreateDirectory(settings.FilesDir);
            Directory.CreateDirectory(settings.LogDir);

            var run = new Run(new SocketInterface(_tcpCommunication, settings.RunId), settings);
            await run.Init();

            return run;
        }

        public void Dispose()
        {
            _manager.Dispose();
            _tcpCommunication.Dispose();
        }
    }
}
