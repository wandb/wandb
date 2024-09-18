using System.Text;


namespace Wandb.Lib
{
    /// <summary>
    /// Provides functionality to generate random strings using a specified alphabet.
    /// </summary>
    public class RandomStringGenerator
    {
        private const string Alphabet = "abcdefghijklmnopqrstuvwxyz1234567890";
        private readonly Random _random;

        public RandomStringGenerator()
        {
            _random = new Random();
        }

        /// <summary>
        /// Generates a random string of the specified length using the defined alphabet.
        /// </summary>
        /// <param name="length">The length of the random string to generate.</param>
        /// <returns>A random string composed of characters from the alphabet.</returns>
        public string GenerateRandomString(int length)
        {
            StringBuilder result = new StringBuilder(length);

            for (int i = 0; i < length; i++)
            {
                result.Append(Alphabet[_random.Next(Alphabet.Length)]);
            }

            return result.ToString();
        }
    }
}
