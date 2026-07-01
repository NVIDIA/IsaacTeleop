# Sample program for Avatar SDK (C++).
# Requires Avatar SDK installed to /opt/avatar-sdk (e.g. via deb package).

CXX = g++
CXXFLAGS = -std=c++17 -g -O0 -Wall -Wextra

INCLUDE_DIR ?= /opt/avatar-sdk/include
LIB_DIR ?= /opt/avatar-sdk/lib
BUILD_DIR ?= $(shell if [ -w . ]; then printf '%s' build; else printf '%s' "$${TMPDIR:-/tmp}/avatar-sdk-sample-cpp"; fi)

# deb / dist ship libavatar_sdk.so (SONAME libavatar_sdk.so)
AVATAR_LIBS = -lavatar_sdk -ldl
RPATH_AVATAR = -Wl,-rpath,$(LIB_DIR)

TARGET_EXAMPLE = $(BUILD_DIR)/avatar_example

$(info Build configuration:)
$(info   INCLUDE_DIR=$(INCLUDE_DIR))
$(info   LIB_DIR=$(LIB_DIR))
$(info   BUILD_DIR=$(BUILD_DIR))

.PHONY: all clean help avatar_example

all: avatar_example

avatar_example: $(TARGET_EXAMPLE)

$(BUILD_DIR):
	@mkdir -p $(BUILD_DIR)

$(TARGET_EXAMPLE): avatar_example.cpp | $(BUILD_DIR)
	@echo "Building avatar_example..."
	$(CXX) $(CXXFLAGS) avatar_example.cpp \
		-I$(INCLUDE_DIR) -L$(LIB_DIR) $(AVATAR_LIBS) \
		$(RPATH_AVATAR) -o $@

clean:
	rm -f $(TARGET_EXAMPLE)
	rm -rf $(BUILD_DIR)

help:
	@echo "Targets:"
	@echo "  all (default)  - build avatar_example into build/"
	@echo "  avatar_example - SDK sample"
	@echo ""
	@echo "Usage:"
	@echo "  ./build/avatar_example /path/to/sdk_config.json [run_seconds]"
