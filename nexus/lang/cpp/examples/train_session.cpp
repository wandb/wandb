#include <fstream>
#include <iostream>

#include <libwandb_cpp.h>

std::string readStringFromFile(const std::string &file_path) {
  std::ifstream input_stream(file_path, std::ios_base::binary);
  if (input_stream.fail()) {
    throw std::runtime_error("could not open file");
  }
  std::string line;
  std::getline(input_stream, line);
  return line;
}

int main() {
  auto wb = new wandb::Session();

  auto apiKey = readStringFromFile("apikey.txt");
  wb->loginSession({
      wandb::session::WithHostname("host"),
      wandb::session::WithAPIKey(apiKey),
  });
  wandb::Config config = {
      {"param1", 4},
      {"param2", 4.2},
      {"param3", "smiles"},
  };
  auto run = wb->initRun({
      wandb::run::WithConfig(config),
  });

  for (int i = 0; i < 5; i++) {
    wandb::History history = {
        {"val", 3.14 + i},
        {"val2", 1.23 + i},
        {"val23", 1},
        {"cat", "dog"},
    };
    run.log(history);
  }

  run.finish();
  return 0;
}
