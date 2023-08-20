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

    // Example data to log
    std::unordered_map<std::string, double> data = {
        {"val", 3.14},
        {"val2", 1.23},
        // Add other data entries as needed
    };
    run.log(data);

    // run.finish();

    return 0;
}
