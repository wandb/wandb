#ifndef LIBWANDB_CPP_H
#define LIBWANDB_CPP_H

#include <string>
#include <unordered_map>
#include <variant>
#include <vector>

namespace wandb {

typedef std::variant<int, double, std::string> Value;
typedef std::unordered_map<std::string, wandb::Value> History;
typedef std::unordered_map<std::string, wandb::Value> Config;

namespace settings {
struct Options {
  bool offline;
  std::string apiKey;
};
} // namespace settings

class Settings {
private:
  bool offline_;
  std::string apiKey;

public:
  Settings();
  Settings(const std::unordered_map<std::string, std::string> &settings_map);
  Settings(const settings::Options &options);
};

namespace run {
class InitRunOption {
protected:
  const Settings *settings;
  const Config *config;
public:
  InitRunOption() : settings(nullptr), config(nullptr) {};
  const Settings *getSettings();
  const Config *getConfig();
};

class WithSettings : public InitRunOption {
public:
  WithSettings(const Settings &s);
};

class WithConfig : public InitRunOption {
public:
  WithConfig(const Config &c);
};
} // namespace run

class Run {
private:
  int _num;

  void logPartialCommit();

  template <typename T>
  void log(std::vector<const char *> &keys, std::vector<T> &values,
           bool commit = false);

public:
  Run();
  Run(const Settings &settings);

  void log(const std::unordered_map<std::string, Value> &values_map);
  void finish();

  friend class Session;
};

class Session {
private:
  static Session *defaultSession_;

  Session(Settings *settings = nullptr);
  Run _initRun(const Settings *settings = nullptr, const Config *config = nullptr);

public:
  Run initRun();
  Run initRun(const std::initializer_list<run::InitRunOption> &options);

  static Session *GetInstance();
};

Run initRun();
Run initRun(const std::initializer_list<run::InitRunOption> &options);

} // namespace wandb

#endif // LIBWANDB_CPP_H
