#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

int main() {
    std::ifstream file("/proc/net/dev");

    if (!file) {
        std::cerr << "Unable to read network statistics\n";
        return 1;
    }

    std::string line;
    std::getline(file, line);
    std::getline(file, line);

    std::uint64_t total_received = 0;
    std::uint64_t total_sent = 0;

    while (std::getline(file, line)) {
        const auto colon = line.find(':');

        if (colon == std::string::npos) {
            continue;
        }

        std::string interface_name = line.substr(0, colon);
        interface_name.erase(
            0, interface_name.find_first_not_of(" \t")
        );
        interface_name.erase(
            interface_name.find_last_not_of(" \t") + 1
        );

        if (interface_name == "lo") {
            continue;
        }

        std::istringstream values(line.substr(colon + 1));
        std::uint64_t received[8]{};
        std::uint64_t transmitted[8]{};

        for (auto& value : received) {
            values >> value;
        }

        for (auto& value : transmitted) {
            values >> value;
        }

        if (!values.fail()) {
            total_received += received[0];
            total_sent += transmitted[0];
        }
    }

    std::cout
        << "{\"bytes_received\":" << total_received
        << ",\"bytes_sent\":" << total_sent
        << ",\"source\":\"cpp\"}\n";
}
