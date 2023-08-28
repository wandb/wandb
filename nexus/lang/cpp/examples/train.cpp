#include <libwandb_cpp.h>

int main() {
  auto run = wandb::initRun();

  for (int i = 0; i < 5; i++) {
    wandb::History history = {
        {"val", 3.14 + i},
        {"val2", 1.23 + i},
        {"val23", 1},
    };
    run.log(history);
  }

  run.finish();
  return 0;
}
