#!/bin/bash

ENV_NAME=hamster-inspect

if ! command -v conda >/dev/null 2>&1; then
	echo "conda not found. Please install Miniconda or Anaconda and initialize conda for your shell." >&2
	exit 1
fi

# Create the environment if it doesn't exist
if ! conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
	echo "Creating conda environment '$ENV_NAME' from environment.yml..."
	conda env create -f environment.yml
else
	echo "Conda environment '$ENV_NAME' already exists."
fi

echo "Activating conda environment '$ENV_NAME'..."
conda activate "$ENV_NAME"

echo "Installing Python packages from requirements.txt..."
pip install -r requirements.txt

echo "Done. To reactivate later: conda activate $ENV_NAME"