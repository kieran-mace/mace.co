library(dplyr)
library(ggplot2)

results_paths = list.files('../output', 'results_[0-9]+.csv', full.names = T)
results = do.call(rbind, lapply(results_paths, read.csv))

	colnames(results) = c('war_anti', 'winner', 'num_turns','player0_mean', paste0("player0_", c(as.character(2:10), 'J', 'Q', 'K', 'A'),'s'))

results %>% ggplot(aes(x =factor(winner), y=player0_mean)) + geom_boxplot() + facet_wrap(~war_anti)
results %>% ggplot(aes(x =factor(winner), y=player0_mean)) + geom_violin()
results %>% ggplot(aes( x=player0_mean)) + geom_histogram()
