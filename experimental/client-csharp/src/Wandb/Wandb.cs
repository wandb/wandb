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

        public async Task<Run> InitRun(
            string? project = null
        )
        {
            if (!_isInitialized)
            {
                var timeout = TimeSpan.FromSeconds(30); // TODO: get from default settings
                _port = await _manager.LaunchCore(timeout);
                await _interface.Initialize(_port.Value);
                _isInitialized = true;
            }
            Console.WriteLine("Project: {0}", project);

            var settings = new Settings(
                project: project
            );

            // Create the run directory structure
            Directory.CreateDirectory(settings.SyncDir);
            Directory.CreateDirectory(settings.FilesDir);
            Directory.CreateDirectory(settings.LogDir);

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
