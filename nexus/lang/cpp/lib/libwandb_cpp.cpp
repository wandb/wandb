#include <stdio.h>
#include <stdlib.h>

#include <libwandb_core.h>
#include <libwandb_cpp.h>

namespace wandb {

// Setup global session
Session *Session::defaultSession_ = nullptr;

Settings::Settings() {}

Settings::Settings(std::unordered_map<std::string, std::string>) {}

Settings::Settings(settings::Options options) {}

Session::Session(Settings *settings) {
  // set static so future calls to functions initRun() have a default session
  defaultSession_ = this;
}

Run::Run() { this->_num = 0; }

void Run::logPartialCommit() { wandbcoreLogCommit(this->_num); }

void Run::log(std::vector<const char *> &keys, std::vector<double> &values,
              bool commit) {
  wandbcoreLogDoubles(this->_num, commit, keys.size(), &keys[0], &values[0]);
}

void Run::log(std::vector<const char *> &keys, std::vector<int> &values,
              bool commit) {
  wandbcoreLogInts(this->_num, commit, keys.size(), &keys[0], &values[0]);
}

void Run::log(std::unordered_map<std::string, Value> &myMap) {
  std::vector<const char *> keyDoubles;
  std::vector<const char *> keyInts;
  std::vector<double> valDoubles;
  std::vector<int> valInts;

  for (const auto &[key, val] : myMap) {
    if (std::holds_alternative<int>(val)) {
      keyInts.push_back(key.c_str());
      valInts.push_back(std::get<int>(val));
    } else if (std::holds_alternative<double>(val)) {
      keyDoubles.push_back(key.c_str());
      valDoubles.push_back(std::get<double>(val));
    }
  }
  if (keyDoubles.size()) {
    this->log(keyDoubles, valDoubles, false);
  }
  if (keyInts.size()) {
    this->log(keyInts, valInts, false);
  }
  this->logPartialCommit();
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

Run Session::_initRun(Settings *settings) {
  _session_setup();
  int n = wandbcoreInit();
  auto r = Run();
  r._num = n;
  return r;
}

Run Session::initRun() { return _initRun(nullptr); }

Run Session::initRun(Settings settings) { return _initRun(&settings); }

Run _initRun(Settings *settings = nullptr) {
  auto s = Session::GetInstance();
  if (settings != nullptr) {
    return s->initRun(*settings);
  }
  return s->initRun();
}

Run initRun(Settings settings) { return _initRun(&settings); }

Run initRun() { return _initRun(nullptr); }

Run initRun(std::initializer_list<run::InitRunOption> options) {
  return _initRun(nullptr);
}

namespace run {
InitRunOption::InitRunOption() {}

WithSettings::WithSettings(Settings s) {}
} // namespace run

} // namespace wandb
