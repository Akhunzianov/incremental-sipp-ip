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
