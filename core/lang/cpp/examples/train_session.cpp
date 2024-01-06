#include <libwandb_cpp.h>

int main() {
  auto wb = new wandb::Session();

  wandb::Config config = {
      {"param1", 4},
      {"param2", 4.2},
      {"param3", "hello"},
  };
  auto run = wb->initRun({
      wandb::run::WithConfig(config), wandb::run::WithProject("myproject"),
      wandb::run::WithRunName("sample run name"),
      // wandb::run::WithRunID("myrunid"),
  });

  for (int i = 0; i < 5; i++) {
    wandb::History history = {
        {"val1", 3.14 + i},
        {"val2", 1.23 + i},
        {"val3", 1},
        {"val4", "data"},
    };
    run.log(history);
  }

  run.finish();
  return 0;
}
