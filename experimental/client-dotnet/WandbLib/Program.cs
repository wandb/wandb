using WandbCoreLib;

// See https://aka.ms/new-console-template for more information
Console.WriteLine("Hello, World!");

var wandb = new WandbCore();

try
{
    // Initialize the WandbCore process and open the socket connection
    wandb.Init();

    // Log a message using WandbCore
    wandb.Log("This is a test log message.");

    // Optionally, you can log more messages as needed
    wandb.Log("Another message to log.");

    // Finish the session and close the connection
    wandb.Finish();
}

catch (Exception ex)
{
    // Handle any exceptions that may occur
    Console.WriteLine($"An error occurred: {ex.Message}");
}
finally
{
    // Ensure the Finish method is called even if an exception occurs
    if (wandb != null)
    {
        wandb.Finish();
    }
}

Console.WriteLine("WandbCore session has completed.");
