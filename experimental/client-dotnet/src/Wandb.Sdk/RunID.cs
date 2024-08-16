using System;
using System.Security.Cryptography;
using System.Text;

public class RandomIdGenerator
{
    private static readonly char[] Alphabet = "abcdefghijklmnopqrstuvwxyz0123456789".ToCharArray();

    public static string GenerateId(int length = 8)
    {
        if (length <= 0) throw new ArgumentException("Length must be greater than zero", nameof(length));

        var result = new StringBuilder(length);
        using (var rng = RandomNumberGenerator.Create())
        {
            byte[] randomBytes = new byte[1];

            for (int i = 0; i < length; i++)
            {
                rng.GetBytes(randomBytes);
                int index = randomBytes[0] % Alphabet.Length;
                result.Append(Alphabet[index]);
            }
        }

        return result.ToString();
    }
}
