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
  std::string name;
  std::string runID;
  std::string project;

public:
  InitRunOption() : settings(nullptr), config(nullptr){};
  const Settings *getSettings();
  const Config *getConfig();
  const std::string getName();
  const std::string getRunID();
  const std::string getProject();
};

class WithSettings : public InitRunOption {
public:
  WithSettings(const Settings &s);
};

class WithConfig : public InitRunOption {
public:
  WithConfig(const Config &c);
};

class WithRunName : public InitRunOption {
public:
  WithRunName(const std::string &n);
};

class WithRunID : public InitRunOption {
public:
  WithRunID(const std::string &i);
};
class WithProject : public InitRunOption {
public:
  WithProject(const std::string &p);
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

namespace session {
// TODO(login): Do not expose loginSession until gowandb login is implemented
// class LoginSessionOption {
// public:
//   LoginSessionOption(){};
// };
//
// class WithAPIKey : public LoginSessionOption {
// public:
//   WithAPIKey(const std::string apiKey);
// };
//
// class WithHostname : public LoginSessionOption {
// public:
//   WithHostname(const std::string hostname);
// };

class SessionOption {
protected:
  const Settings *settings;

public:
  SessionOption(){};
};

class WithSettings : public SessionOption {
public:
  WithSettings(const Settings &s);
};

} // namespace session

class Session {
private:
  static Session *defaultSession_;

  Run _initRun(const Settings *settings = nullptr,
               const Config *config = nullptr, const std::string name = "",
               const std::string runID = "", const std::string project = "");

public:
  Session(Settings *settings = nullptr);
  Run initRun();
  Run initRun(const std::initializer_list<run::InitRunOption> &options);
  // TODO(login): Do not expose loginSession until gowandb login is implemented
  // void loginSession(
  //     const std::initializer_list<session::LoginSessionOption> &options);

  static Session *GetInstance();
};

Run initRun();
Run initRun(const std::initializer_list<run::InitRunOption> &options);

} // namespace wandb

#endif // LIBWANDB_CPP_H
