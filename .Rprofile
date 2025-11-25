# Workaround for pak subprocess failure (pak#325, renv#1628)
# pak's subprocess loads .Rprofile, causing recursive activation loop.
# Pre-installing pak avoids the bootstrap. Remove once renv/pak fix this upstream.
# See: https://github.com/r-lib/pak/issues/325
if (!requireNamespace("pak", quietly = TRUE)) {
  install.packages("pak", repos = "https://r-lib.github.io/p/pak/devel/")
}

options(renv.config.pak.enabled = TRUE)
source("renv/activate.R")
