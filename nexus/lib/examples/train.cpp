#include <libwandbpp.h>

int main() {
    wandb::Settings settings({
        {"setting1", "this"},
        {"setting2", "that"},
        // Add more settings as needed
    });

    auto session = wandb::Session(settings);

    // Initialize run with settings
    wandb::Run run = session.initRun(settings);

    for (int i = 0; i < 5; i++) {
        // Example data to log
        std::unordered_map<std::string, double> data = {
            {"val", 3.14 + i},
            {"val2", 1.23 + i},
        };
        run.log(data);
    }

    // Complete the run
    run.finish();

    return 0;
}
