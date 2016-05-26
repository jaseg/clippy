
all: pixelflut.so


pixelflut.so: pixelflut.c
	gcc -o $@ -shared -fPIC -Wall -Wpedantic -Wstrict-aliasing $<


.PHONY: clean
clean:
	rm -f pixelflut.so
