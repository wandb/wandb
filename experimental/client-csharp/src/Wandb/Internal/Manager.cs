using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Threading.Tasks;

namespace Wandb.Core
{
    public class WandbManager : IDisposable
    {
        private Process? _coreProcess;
        private string _portFilePath;

        public WandbManager()
        {
            _portFilePath = Path.Combine(Path.GetTempPath(), $"port-{Process.GetCurrentProcess().Id}.txt");
        }

        public async Task<int> LaunchCore(TimeSpan timeout)
        {
            File.Create(_portFilePath).Dispose(); // Create empty file

            _coreProcess = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName = "wandb-core",
                    Arguments = $"--port-filename {_portFilePath} --pid {Process.GetCurrentProcess().Id} --serve-sock",
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true
                }
            };

            _coreProcess.Start();

            return await WaitForPort(timeout);
        }

        private async Task<int> WaitForPort(TimeSpan timeout)
        {
            var startTime = DateTime.Now;
            var delayTime = TimeSpan.FromMilliseconds(20);

            while (DateTime.Now - startTime < timeout)
            {
                await Task.Delay(delayTime);

                if (!File.Exists(_portFilePath))
                    continue;

                var contents = await File.ReadAllTextAsync(_portFilePath);
                var lines = contents.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);

                if (lines.Length > 0 && lines[^1] == "EOF")
                {
                    foreach (var line in lines)
                    {
                        var parts = line.Split('=');
                        if (parts.Length == 2 && parts[0] == "sock")
                        {
                            if (int.TryParse(parts[1], out int port))
                            {
                                return port;
                            }
                            throw new InvalidOperationException("Failed to parse port number");
                        }
                    }
                }
            }

            throw new TimeoutException("Timed out waiting for wandb-core to write port number");
        }

        public void Dispose()
        {
            _coreProcess?.Kill();
            _coreProcess?.Dispose();
            File.Delete(_portFilePath);
        }
    }
}
