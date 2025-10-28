#!/bin/bash

set -e

# Make sure to run this script from the root of the repository.
GIT_ROOT=$(git rev-parse --show-toplevel)
cd "$GIT_ROOT" || exit 1

ENV_FILE="deps/cloudxr/.env"

# 1. Check if .env file exists
if [ ! -f "$ENV_FILE" ]; then
    echo "Error: $ENV_FILE not found. Please create it first."
    exit 1
fi

# 2. Check if ACCEPT_CLOUDXR_EULA is set to Y
if grep -q "^ACCEPT_CLOUDXR_EULA=Y$" "$ENV_FILE"; then
    echo "CloudXR EULA already accepted."
    exit 0
fi

# 2b. Prompt user to accept EULA
echo "By installing or using NVIDIA CloudXR, I agree to the terms of
NVIDIA CloudXR LICENSE AGREEMENT (EULA) in
https://github.com/nvidia-isaac/TeleopCore/blob/main/deps/cloudxr/CLOUDXR_LICENSE"
echo "Do you accept the EULA? (Yes/No)"

echo -n "Type 'yes' to accept: "
read -r response

# 3. Handle user response
if [ "$response" = "yes" ]; then
    # 3a. Update or add ACCEPT_CLOUDXR_EULA=Y to .env file
    if grep -q "^ACCEPT_CLOUDXR_EULA=" "$ENV_FILE"; then
        # Update existing line
        sed -i 's/^ACCEPT_CLOUDXR_EULA=.*/ACCEPT_CLOUDXR_EULA=Y/' "$ENV_FILE"
    else
        # Add new line
        echo "ACCEPT_CLOUDXR_EULA=Y" >> "$ENV_FILE"
    fi
    exit 0
else
    # 3b. Exit with error if not accepted
    echo "CloudXR EULA not accepted. Exiting."
    exit 1
fi

