using System.Text;


namespace Wandb.Lib
{
    public class RandomStringGenerator
    {
        private const string Alphabet = "abcdefghijklmnopqrstuvwxyz1234567890";
        private readonly Random _random;

        public RandomStringGenerator()
        {
            _random = new Random();
        }

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
