CONFIG ?= config/stoker-build.yaml

.PHONY: validate render resolve repository extract inject checksum package verify build test clean
validate:
	./build.sh -c $(CONFIG) validate
render:
	./build.sh -c $(CONFIG) render
resolve:
	./build.sh -c $(CONFIG) resolve
repository:
	./build.sh -c $(CONFIG) repository
extract:
	./build.sh -c $(CONFIG) extract
inject:
	./build.sh -c $(CONFIG) inject
checksum:
	./build.sh -c $(CONFIG) checksum
package:
	./build.sh -c $(CONFIG) package
verify:
	./build.sh -c $(CONFIG) verify
build:
	./build.sh -c $(CONFIG) all
test:
	python3 -m pytest -q
clean:
	./build.sh -c $(CONFIG) clean
