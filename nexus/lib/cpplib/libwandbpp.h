#include <string>
#include <unordered_map>

namespace wandb {

class Settings {
public:
  Settings();
  Settings(std::unordered_map<std::string, std::string>);
private:
  std::unordered_map<std::string, std::string> mymap;
};

class Run {
public:
  int _num;
  Run();
  Run(Settings settings);
  void log(std::unordered_map<std::string, double>&);
  void finish();
};

Run initRun();
Run initRun(Settings settings);

}
