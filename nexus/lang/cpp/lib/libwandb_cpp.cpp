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
  std::vector<double> valDoubles;
  std::vector<int> valInts;

  for (const auto &[key, val] : *myMap) {
    if (std::holds_alternative<int>(val)) {
      keyInts.push_back(key.c_str());
      valInts.push_back(std::get<int>(val));
    } else if (std::holds_alternative<double>(val)) {
      keyDoubles.push_back(key.c_str());
      valDoubles.push_back(std::get<double>(val));
    }
  }
  int data_num = WANDBCORE_DATA_CREATE;
  if (keyDoubles.size()) {
    data_num = wandbcoreDataAddDoubles(data_num, keyDoubles.size(), &keyDoubles[0], &valDoubles[0]);
  }
  if (keyInts.size()) {
    data_num = wandbcoreDataAddInts(data_num, keyInts.size(), &keyInts[0], &valInts[0]);
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

Run Session::_initRun(Settings *settings, Config *config) {
  _session_setup();

  auto configData = new Data(config);
  int n = wandbcoreInit(configData->num);
  Run r;
  r._num = n;
  return r;
}

Run Session::initRun(const std::initializer_list<run::InitRunOption> &options) {
  Settings *settings;
  Config *config;
  for (auto item : options) {
      auto withSettings = static_cast<run::WithSettings *>(&item);
      if (withSettings != nullptr) {
          settings = withSettings->getSettings();
      }
      auto withConfig = static_cast<run::WithConfig *>(&item);
      if (withConfig != nullptr) {
          config = withConfig->getConfig();
      }
  }
  return this->_initRun(settings, config);
}

Run Session::initRun() {
  return this->initRun({});
}

Run initRun(const std::initializer_list<run::InitRunOption> &options) {
  auto s = Session::GetInstance();
  return s->initRun(options);
}

Run initRun() {
  return initRun({});
}

namespace run {
Settings *InitRunOption::getSettings() {
    return this->settings;
}
Config *InitRunOption::getConfig() {
    return this->config;
}
WithSettings::WithSettings(const Settings &s) {
    this->settings = settings;
}
WithConfig::WithConfig(const Config &c) {
    this->config = config;
}

} // namespace run

} // namespace wandb
