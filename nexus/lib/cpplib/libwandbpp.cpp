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

void Run::log(std::vector<const char *>& keys, std::vector<double>& values)
{
    wandbcoreLogDoubles(this->_num, 1, keys.size(), &keys[0], &values[0]);
}

void Run::log(std::unordered_map<std::string, double>& myMap)
{
    std::vector<const char *> keys;
    std::vector<double> values;
    keys.reserve(myMap.size());
    values.reserve(myMap.size());

    for ( const auto &[key, value] : myMap ) {
	keys.push_back(key.c_str());
	values.push_back(value);
    }
    this->log(keys, values);

    /*
    std::string key = "junk";
    wandbcoreLogScaler(this->_num, (char *)key.c_str(), 2.3);
    int count = 3;
    char *keys[3];
    double vals[3];
    int i;
    char buf[80];
    for (i=0; i < count; i++) {
	sprintf(buf, "junk%d", i);
        keys[i] = strdup(buf);
	vals[i] = i*2.5;
    }
    wandbcoreLogDoubles(this->_num, 0, count, keys, vals);
    */
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
