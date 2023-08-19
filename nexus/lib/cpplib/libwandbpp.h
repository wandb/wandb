#include <string>
#include <unordered_map>

namespace wandb {

class Settings {
private:
  std::unordered_map<std::string, std::string> settings;
public:
  Settings();
  Settings(std::unordered_map<std::string, std::string>);
};

class Run {
protected:
  int _num;
public:
  Run();
  Run(Settings settings);
  void log(std::unordered_map<std::string, double>&);
  void finish();
  friend class Session;
};

class Session {
private:
  Run _initRun(Settings *settings);
public:
  Session();
  Session(Settings settings);
  Run initRun();
  Run initRun(Settings settings);
};


}
