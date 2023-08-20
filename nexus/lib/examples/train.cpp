#include <libwandbpp.h>

int main() {
    wandb::Settings settings(
        (wandb::settings::Options){
            .offline = false,
        }
    );

    auto run = wandb::initRun({
            wandb::run::WithSettings(settings),
        });

    for (int i = 0; i < 5; i++) {
        wandb::History data = {
            {"val", 3.14 + i},
            {"val2", 1.23 + i},
            {"val23", int(1)},
        };
        run.log(data);
    }

    run.finish();

    return 0;
}
