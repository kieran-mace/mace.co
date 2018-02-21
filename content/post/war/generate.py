# ---- sim ----

import numpy as np
import pandas as pd
from game import *

for ante in range(0,11):
    games = [Game(ante) for i in range(0,10000)]
    [g.play() for g in games]
    all = [[g.war_ante, g.winner, g.num_turns, np.mean(g.p0_start)] + [g.p0_start.count(c) for c in range(1,14)] for g in games]
    all_df = pd.DataFrame.from_records(all)
    all_df.to_csv('output/results_' + str(anti) + '.csv', index = False)
