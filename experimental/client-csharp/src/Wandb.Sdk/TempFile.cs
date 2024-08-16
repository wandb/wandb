using System;
using System.IO;

public class TempFileHelper : IDisposable
{
    public string FilePath { get; private set; }
    private string DirectoryPath { get; set; }
    private bool disposed = false;

    public TempFileHelper(string fixedFileName)
    {
        if (string.IsNullOrWhiteSpace(fixedFileName))
        {
            throw new ArgumentException("File name cannot be null or empty.", nameof(fixedFileName));
        }

        // Get the system temporary directory path
        string tempPath = Path.GetTempPath();

        // Generate a random directory name
        DirectoryPath = Path.Combine(tempPath, Path.GetRandomFileName());

        // Create the random directory
        Directory.CreateDirectory(DirectoryPath);

        // Combine the random directory path with the provided fixed file name
        FilePath = Path.Combine(DirectoryPath, fixedFileName);

        // Optionally, create the file now if you want it to exist
        using (var fileStream = File.Create(FilePath)) { }
    }

    // Implement IDisposable to clean up the directory
    public void Dispose()
    {
        Dispose(true);
        GC.SuppressFinalize(this);
    }

    protected virtual void Dispose(bool disposing)
    {
        if (!disposed)
        {
            if (disposing)
            {
                // Delete the file and directory if they exist
                if (File.Exists(FilePath))
                {
                    File.Delete(FilePath);
                }
                if (Directory.Exists(DirectoryPath))
                {
                    Directory.Delete(DirectoryPath, true);
                }
            }

            disposed = true;
        }
    }

    ~TempFileHelper()
    {
        Dispose(false);
    }
}
