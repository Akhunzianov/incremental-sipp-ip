.PHONY: build test demo clean
build:
	python3 -m sipp_baseline build
	python3 -m sipp_baseline build-incremental
test: build
	python3 -m unittest discover -s tests -v
demo: build
	python3 -m sipp_baseline run examples/corridor.json --output runs/corridor --oracle
clean:
	rm -rf build

.PHONY: build-adaptive
build-adaptive: build/sipp_ip_adaptive

build/sipp_ip_adaptive: src/incremental.cpp src/fresh.hpp src/model.hpp
	mkdir -p build
	g++ -std=c++17 -O3 -DNDEBUG -Wall -Wextra -Wpedantic -DSIPP_ADAPTIVE src/incremental.cpp -o $@
