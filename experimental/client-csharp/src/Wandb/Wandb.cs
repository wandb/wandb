using Wandb.Internal;

namespace Wandb
{
    public class Session : IDisposable
    {
        private readonly Manager _manager;
        private readonly SocketInterface _interface;
        private bool _isInitialized = false;
        private int? _port = null;

        public Session()
        {
            _manager = new Manager();
            _interface = new SocketInterface();
        }

        public async Task<Run> InitRun()
        {
            if (!_isInitialized)
            {
                var timeout = TimeSpan.FromSeconds(30); // Adjust as needed
                _port = await _manager.LaunchCore(timeout);
                await _interface.Initialize(_port.Value);
                _isInitialized = true;
            }

            RandomStringGenerator generator = new();
            string runId = generator.GenerateRandomString(8);

            // TODO: do not hardcode stuff
            string timespec = DateTime.Now.ToString("yyyyMMdd_HHmmss");

            var settings = new Settings(
                runId: runId,
                timespec: timespec
            );

            // Create the run directory structure
            Directory.CreateDirectory(settings.GetSyncDir());
            Directory.CreateDirectory(settings.GetFilesDir());
            Directory.CreateDirectory(settings.GetLogDir());

            var run = new Run(_interface, settings);
            await run.Init();

            return run;
        }

        public void Dispose()
        {
            _manager.Dispose();
            _interface.Dispose();
        }
    }
}
