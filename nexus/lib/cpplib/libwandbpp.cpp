#include <stdio.h>
#include <stdlib.h>
#include <libwandbpp.h>
#include <libwandbcore.h>

namespace wandb {

Settings::Settings()
{
}

Settings::Settings(std::unordered_map<std::string, std::string>)
{
}

Session::Session()
{
}

Session::Session(Settings settings)
{
}

Run::Run()
{
    this->_num = 0;
}

void Run::log(std::unordered_map<std::string, double>&)
{
    std::string key = "junk";
    wandbcoreLogScaler(this->_num, (char *)key.c_str(), 2.3);
}

void Run::finish()
{
    wandbcoreFinish(this->_num);
}

void _session_teardown() {
    wandbcoreTeardown();
}

void _session_setup() {
    wandbcoreSetup();
    atexit(_session_teardown);
}

Run Session::_initRun(Settings *settings = NULL) {
    _session_setup();
    int n = wandbcoreInit();
    auto r = Run();
    r._num = n;
    return r;
}

Run Session::initRun() {
    return _initRun(NULL);
}

Run Session::initRun(Settings settings) {
    return _initRun(&settings);
}

}
