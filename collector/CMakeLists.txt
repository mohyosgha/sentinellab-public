cmake_minimum_required(VERSION 3.16)
project(SentinelCollector LANGUAGES CXX)

add_executable(network_collector main.cpp)
target_compile_features(network_collector PRIVATE cxx_std_17)
