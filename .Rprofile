# renv activation with pak support
#
# The pak workaround below is only needed for LOCAL development due to
# pak#325 / renv#1628 (pak subprocess recursively loads .Rprofile).
# In CI, renv::restore() handles everything - no pak pre-install needed.
#
# We detect CI via the CI environment variable (set by GitHub Actions, etc.)

# Enable Posit Package Manager for pre-compiled binary packages
options(renv.config.ppm.enabled = TRUE)

if (!nzchar(Sys.getenv("CI"))) {

  # LOCAL: Pre-install pak to avoid subprocess bootstrap issues
  # See: https://github.com/r-lib/pak/issues/325
  if (!requireNamespace("pak", quietly = TRUE)) {
    utils::install.packages("pak", repos = "https://r-lib.github.io/p/pak/devel/")
  }
  options(renv.config.pak.enabled = TRUE)
}

source("renv/activate.R")
