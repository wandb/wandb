#include <string>
#include <variant>
#include <vector>
#include <unordered_map>

namespace wandb {

typedef std::variant<
  int,
  float,
  double
  > Value;

namespace settings {
typedef struct settings_options_s {
    bool offline;
    std::string apiKey;
}Options;
}

class Settings {
private:
  bool offline_;
  std::string apiKey;
public:
  Settings();
  Settings(std::unordered_map<std::string, std::string>);
  Settings(settings::Options);
};

class Run {
private:
  void log(std::vector<const char *>&, std::vector<double>&, bool commit = false);
  void log(std::vector<const char *>&, std::vector<int>&, bool commit = false);
  void logPartialCommit();
protected:
  int _num;
public:
  Run();
  Run(Settings settings);
  void log(std::unordered_map<std::string, Value>&);
  // void log(std::vector<const char *>&, std::vector<Value>&);
  void finish();
  friend class Session;
};

class Session {
private:
  Run _initRun(Settings *settings = NULL);
  static Session *defaultSession_;
  Session(Settings *settings = NULL);
public:
  Session() : Session(NULL) {}
  Session(Settings settings) : Session(&settings) {}
  Run initRun();
  Run initRun(Settings settings);
  static Session *GetInstance();
};

Run initRun(Settings settings);
Run initRun();

}
