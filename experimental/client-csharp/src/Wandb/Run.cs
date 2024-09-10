using System;
using System.Text;
using System.Threading.Tasks;
using WandbInternal;
using Wandb.Internal;

namespace Wandb
{
    public class Run : IDisposable
    {
        private readonly SocketInterface _interface;
        public Settings Settings;

        internal Run(SocketInterface @interface, Settings settings)
        {
            _interface = @interface;
            Settings = settings;
        }

        public async Task Init()
        {
            await _interface.InformInit(Settings);
            Result deliverRunResult = await _interface.DeliverRun(this);
            if (deliverRunResult.RunResult == null)
            {
                throw new Exception("Failed to deliver run");
            }

            RunUpdateResult runResult = deliverRunResult.RunResult;
            if (runResult.Error != null)
            {
                throw new Exception(runResult.Error.Message);
            }

            // save project, entity and displa name to settings
            Settings.Project = runResult.Run.Project;
            Settings.Entity = runResult.Run.Entity;
            Settings.DisplayName = runResult.Run.DisplayName;
            Result result = await _interface.DeliverRunStart(this);
            if (result.Response == null)
            {
                throw new Exception("Failed to deliver run start");
            }
            printRunURL();
        }


        public async Task Log(Dictionary<string, object> data)
        {
            await _interface.PublishPartialHistory(data);
        }

        public async Task Finish()
        {
            Result deliverExitResult = await _interface.DelieverExit();
            if (deliverExitResult.ExitResult == null)
            {
                throw new Exception("Failed to deliver exit");
            }
            // Send finish command
            await _interface.InformFinish();
            printRunURL();
            printRunDir();
        }

        private void printRunURL()
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

        private void printRunDir()
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

        public void Dispose()
        {
            _interface.Dispose();
        }
    }
}
