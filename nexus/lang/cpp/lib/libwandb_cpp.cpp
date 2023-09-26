#include "libwandb_cpp.h"
#include <libwandb_core.h>
#include <stdio.h>
#include <stdlib.h>

namespace wandb {

// Setup global session
Session *Session::defaultSession_ = nullptr;

Settings::Settings() {}

Settings::Settings(const std::unordered_map<std::string, std::string> &) {}

Settings::Settings(const settings::Options &options) {}

Session::Session(Settings *settings) {
  // set static so future calls to functions initRun() have a default session
  defaultSession_ = this;
}

class Data {
public:
  int num;
  Data();
  Data(const std::unordered_map<std::string, Value> *myMap);
  ~Data();
};

Data::Data(const std::unordered_map<std::string, Value> *myMap) : num(0) {
  if (myMap == nullptr) {
    return;
  }
  std::vector<const char *> keyDoubles;
  std::vector<const char *> keyInts;
  std::vector<const char *> keyStrings;
  std::vector<double> valDoubles;
  std::vector<int> valInts;
  std::vector<const char *> valStrings;

  for (const auto &[key, val] : *myMap) {
    if (std::holds_alternative<int>(val)) {
      keyInts.push_back(key.c_str());
      valInts.push_back(std::get<int>(val));
    } else if (std::holds_alternative<double>(val)) {
      keyDoubles.push_back(key.c_str());
      valDoubles.push_back(std::get<double>(val));
    } else if (std::holds_alternative<std::string>(val)) {
      keyStrings.push_back(key.c_str());
      valStrings.push_back(std::get<std::string>(val).c_str());
    }
  }
  int data_num = WANDBCORE_DATA_CREATE;
  if (keyDoubles.size()) {
    data_num = wandbcoreDataAddDoubles(data_num, keyDoubles.size(),
                                       &keyDoubles[0], &valDoubles[0]);
  }
  if (keyInts.size()) {
    data_num = wandbcoreDataAddInts(data_num, keyInts.size(), &keyInts[0],
                                    &valInts[0]);
  }
  if (keyStrings.size()) {
    data_num = wandbcoreDataAddStrings(data_num, keyStrings.size(),
                                       &keyStrings[0], &valStrings[0]);
  }
  this->num = data_num;
}

Data::~Data() {
  if (this->num == 0) {
    return;
  }
  wandbcoreDataFree(this->num);
}

Run::Run() : _num(0) {}

void Run::log(const std::unordered_map<std::string, Value> &myMap) {
  auto data = new Data(&myMap);
  wandbcoreLogData(this->_num, data->num);
}

void Run::finish() { wandbcoreFinish(this->_num); }

void _session_teardown() { wandbcoreTeardown(); }

void _session_setup() {
  wandbcoreSetup();
  atexit(_session_teardown);
}

Session *Session::GetInstance() {
  if (defaultSession_ == nullptr) {
    new Session(nullptr);
  }
  return defaultSession_;
}

Run Session::_initRun(const Settings *settings, const Config *config, const std::string *name, const std::string *runID) {
  _session_setup();

  auto configData = new Data(config);
  const char *cName = NULL;
  const char *cRunID = NULL;
  if (name != nullptr) {
      cName = name->c_str();
  }
  if (runID != nullptr) {
      cRunID = runID->c_str();
  }
  int n = wandbcoreInit(configData->num, cName, cRunID);
  Run r;
  r._num = n;
  return r;
}

Run Session::initRun(const std::initializer_list<run::InitRunOption> &options) {
  const Settings *settings;
  const Config *config;
  const std::string *name;
  const std::string *runID;
  for (auto item : options) {
    auto withSettings = static_cast<run::WithSettings *>(&item);
    if (withSettings != nullptr) {
      settings = withSettings->getSettings();
    }
    auto withConfig = static_cast<run::WithConfig *>(&item);
    if (withConfig != nullptr) {
      config = withConfig->getConfig();
    }
    auto withName = static_cast<run::WithName *>(&item);
    if (withName != nullptr) {
      name = withName->getName();
    }
    auto withRunID = static_cast<run::WithRunID *>(&item);
    if (withRunID != nullptr) {
      runID = withRunID->getRunID();
    }
  }
  return this->_initRun(settings, config, name, runID);
}

namespace session {
WithAPIKey::WithAPIKey(const std::string apiKey){};

WithHostname::WithHostname(const std::string hostname){};
} // namespace session

void Session::loginSession(
    const std::initializer_list<session::LoginSessionOption> &options) {}

Run Session::initRun() { return this->initRun({}); }

Run initRun(const std::initializer_list<run::InitRunOption> &options) {
  auto s = Session::GetInstance();
  return s->initRun(options);
}

Run initRun() { return initRun({}); }

namespace run {
const Settings *InitRunOption::getSettings() { return this->settings; }
const Config *InitRunOption::getConfig() { return this->config; }
WithSettings::WithSettings(const Settings &s) { this->settings = &s; }
WithConfig::WithConfig(const Config &c) { this->config = &c; }
WithName::WithName(const std::string &n) { this->name = &n; }
WithRunID::WithRunID(const std::string &i) { this->runID = &i; }

} // namespace run

} // namespace wandb
