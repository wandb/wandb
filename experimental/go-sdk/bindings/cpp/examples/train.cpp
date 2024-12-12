#include <libwandb_cpp.h>

int main() {
  wandb::Config config = {
      {"param1", 4},
      {"param2", 4.2},
      {"param3", "smiles"},
  };
  auto run = wandb::initRun({
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
