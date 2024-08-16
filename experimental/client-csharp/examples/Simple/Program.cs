using Wandb.Sdk;
using System.Collections.Generic;

// See https://aka.ms/new-console-template for more information
Console.WriteLine("Hello, World!");

var wandb = new WandbClient();

try
{
    // Initialize the WandbCore process and open the socket connection
    wandb.Init();

    // Log a message using WandbCore
    var logData = new Dictionary<string, object>
    {
        { "accuracy", 0.95 },
        { "epoch", 3 },
        { "loss", 0.123 },
    };
    wandb.Log(logData);
    wandb.Log(logData);

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
