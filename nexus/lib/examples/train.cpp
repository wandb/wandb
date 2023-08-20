#include <libwandbpp.h>
#include <iostream>

int main() {
    wandb::Settings settings(
        (wandb::settings::Options){
	    .offline = false,
	}
    );

    // auto session = wandb::Session(settings);

    // Initialize run with settings
    // wandb::Run run = session.initRun(settings);
    auto run = initRun(settings);

    for (int i = 0; i < 5; i++) {
        // Example data to log
        std::unordered_map<std::string, wandb::Value> data = {
            {"val", 3.14 + i},
            {"val2", 1.23 + i},
            {"val23", int(1)},
        };
        run.log(data);
    }

    // Complete the run
    run.finish();

    return 0;
}
