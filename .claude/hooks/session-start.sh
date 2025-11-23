#!/bin/bash
set -euo pipefail

# Only run in Claude Code on the web
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

echo "Setting up Quarto blog environment..."

# Install R if not present
if ! command -v R &> /dev/null; then
  echo "Installing R..."
  sudo apt-get update -qq > /dev/null 2>&1
  sudo apt-get install -y -qq \
    r-base \
    r-base-dev \
    libcurl4-openssl-dev \
    libssl-dev \
    libxml2-dev \
    libfontconfig1-dev \
    libharfbuzz-dev \
    libfribidi-dev \
    libfreetype6-dev \
    libpng-dev \
    libtiff5-dev \
    libjpeg-dev > /dev/null 2>&1
  echo "R installed successfully."
else
  echo "R already installed."
fi

# Install Python packages if not present
echo "Installing Python packages..."
pip3 install --quiet --upgrade numpy pandas matplotlib 2>&1 | grep -v "Requirement already satisfied" || true

# Install R packages
echo "Installing R packages..."
Rscript -e '
  repos <- "https://cloud.r-project.org"

  # Function to install if not already installed
  install_if_missing <- function(pkg) {
    if (!require(pkg, character.only = TRUE, quietly = TRUE)) {
      cat(sprintf("Installing %s...\n", pkg))
      install.packages(pkg, repos = repos, quiet = TRUE)
    }
  }

  # Core packages needed for the blog
  packages <- c(
    "tidyverse",    # Data manipulation and ggplot2
    "scales",       # Scale functions for ggplot2
    "viridis",      # Color palettes
    "reticulate",   # Python integration
    "knitr",        # Knitting documents
    "rmarkdown"     # R Markdown support
  )

  invisible(lapply(packages, install_if_missing))
  cat("R packages ready.\n")
' 2>&1 | grep -E "(Installing|ready)" || true

# Install Quarto if not present
if ! command -v quarto &> /dev/null; then
  echo "Installing Quarto..."
  QUARTO_VERSION="1.4.553"
  cd /tmp
  wget -q "https://github.com/quarto-dev/quarto-cli/releases/download/v${QUARTO_VERSION}/quarto-${QUARTO_VERSION}-linux-amd64.deb"
  sudo dpkg -i "quarto-${QUARTO_VERSION}-linux-amd64.deb" > /dev/null 2>&1
  rm "quarto-${QUARTO_VERSION}-linux-amd64.deb"
  cd "$CLAUDE_PROJECT_DIR"
fi

# Verify installations
echo "Verifying installations..."
quarto --version
R --version | head -n1
python3 -c "import numpy, pandas, matplotlib; print('Python packages: OK')"

echo "✅ Environment setup complete!"
