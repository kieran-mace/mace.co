"""
Monte Carlo simulator for a 13-round Swiss rapid event:
- Scrapes "Ranking crosstable after Round 9" and "Round 10 pairings" from Chess-Results
- Simulates rounds 10-13:
    * Round 10 uses the published pairings
    * Rounds 11-13 re-pair using a simplified Swiss approximation (score groups + rating sort + floaters)
- Uses an Elo-style win/draw/loss probability model with a tunable draw rate

Sources (as of Dec 27/28, 2025):
- Crosstable after Round 9: https://s2.chess-results.com/tnr1313074.aspx?art=4&flag=30&lan=1&turdet=YES&SNode=S0
- Round 10 pairings:       https://chess-results.com/tnr1313074.aspx?art=2&flag=30&lan=1&rd=10&turdet=YES
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd

# ----------------------------
# 1) Scraping helpers
# ----------------------------

CROSSTABLE_URL = "https://s2.chess-results.com/tnr1313074.aspx?art=4&flag=30&lan=1&turdet=YES&SNode=S0"
RD10_PAIRINGS_URL = "https://chess-results.com/tnr1313074.aspx?art=2&flag=30&lan=1&rd=10&turdet=YES"


def parse_chess_points(pts_str: str) -> float:
    """
    Parse chess points from various formats:
    - "7" -> 7.0
    - "7.5" -> 7.5
    - "7,5" -> 7.5
    - "7½" -> 7.5
    - "75" (when scraped as 7 5) -> 7.5
    - "65" (when scraped as 6 5) -> 6.5
    """
    if pd.isna(pts_str):
        return np.nan

    s = str(pts_str).strip()

    # Handle ½ character
    if "½" in s:
        s = s.replace("½", ".5")

    # Handle comma decimal separator
    s = s.replace(",", ".")

    # Handle space-separated (e.g., "7 5" for 7.5)
    s = s.replace(" ", ".")

    # If it looks like a two-digit integer ending in 5, it might be X.5
    # e.g., "75" should be 7.5, "65" should be 6.5
    if s.isdigit() and len(s) == 2 and s.endswith("5"):
        s = s[0] + ".5"

    # Similarly for 3-digit like "105" -> 10.5
    if s.isdigit() and len(s) == 3 and s.endswith("5"):
        s = s[:2] + ".5"

    try:
        return float(s)
    except ValueError:
        return np.nan


def load_crosstable_after_rd9(url: str = CROSSTABLE_URL) -> pd.DataFrame:
    """
    Returns a dataframe with at least:
      - Name
      - Rtg
      - Pts.
      - Rk.
    """
    tables = pd.read_html(url)
    # Chess-Results often puts the main crosstable as the first large table after headers.
    # We'll take the largest table by column count as a robust heuristic.
    ctab = max(tables, key=lambda t: t.shape[1])
    # Normalize column names
    ctab.columns = [str(c).strip().replace("\xa0", " ") for c in ctab.columns]
    # Keep only the key fields; tolerate minor header differences
    # Expecting columns like: "Rk.", "Name", "Rtg", "FED", ..., "Pts."
    needed = []
    for cand in ["Rk.", "Rk", "Rank", "Rk. "]:
        if cand in ctab.columns:
            needed.append(cand)
            break
    for cand in ["Name", "Name "]:
        if cand in ctab.columns:
            needed.append(cand)
            break
    for cand in ["Rtg", "Rtg "]:
        if cand in ctab.columns:
            needed.append(cand)
            break
    for cand in ["Pts.", "Pts", "Points", "Pts. "]:
        if cand in ctab.columns:
            needed.append(cand)
            break

    if len(needed) < 4:
        raise ValueError(f"Could not find expected columns in crosstable. Columns: {ctab.columns.tolist()}")

    df = ctab[needed].copy()
    df.columns = ["rank", "name", "rtg", "pts"]

    # Clean data types
    df["rank"] = pd.to_numeric(df["rank"], errors="coerce")
    df["rtg"] = pd.to_numeric(df["rtg"], errors="coerce")

    # Parse points using our custom parser that handles various formats
    df["pts"] = df["pts"].apply(parse_chess_points)

    # Drop rows that are not real players
    df = df.dropna(subset=["name", "rtg", "pts"]).reset_index(drop=True)

    # Standardize name spacing and convert to "LastName FirstName" format
    df["name"] = df["name"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    # Remove asterisks and other markers
    df["name"] = df["name"].str.replace(r"\s*\*\)?", "", regex=True).str.strip()
    # Convert "LastName, FirstName" to "LastName FirstName"
    df["name"] = df["name"].str.replace(", ", " ", regex=False)

    return df


def load_round_pairings(url: str = RD10_PAIRINGS_URL) -> pd.DataFrame:
    """
    Scrapes the round pairing table from Chess-Results.
    The table structure is:
    [Bo., No., (empty), (GM), White, Rtg, Pts., Result, Pts., (empty), Black, Rtg, (empty), No.]

    Returns columns:
      - board
      - white
      - black
      - white_rtg
      - black_rtg
      - white_pts
      - black_pts
    """
    tables = pd.read_html(url)

    # Find the largest table with 14 columns (the pairings table)
    pairing = None
    for t in tables:
        if t.shape[1] >= 12:  # Pairings table has many columns
            # Check if first row contains "White" and "Black"
            first_row = t.iloc[0].astype(str).tolist()
            if any("White" in str(v) for v in first_row) and any("Black" in str(v) for v in first_row):
                pairing = t.copy()
                break

    if pairing is None:
        raise ValueError("Could not find pairing table on the page.")

    # The first row is the header - use it to set column names
    header_row = pairing.iloc[0].astype(str).tolist()

    # Drop the header row
    pairing = pairing.iloc[1:].reset_index(drop=True)

    # The table structure (by index):
    # 0: Bo. (board number)
    # 1: No. (player number)
    # 2: empty
    # 3: title (GM, IM, etc)
    # 4: White name
    # 5: Rtg
    # 6: Pts.
    # 7: Result
    # 8: Pts.
    # 9: empty
    # 10: Black name
    # 11: Rtg
    # 12: empty
    # 13: No.

    # Find indices by looking at header
    white_idx = next((i for i, h in enumerate(header_row) if "White" in h), 4)
    black_idx = next((i for i, h in enumerate(header_row) if "Black" in h), 10)

    df = pd.DataFrame({
        "board": pairing.iloc[:, 0],
        "white": pairing.iloc[:, white_idx],
        "white_rtg": pairing.iloc[:, white_idx + 1],
        "white_pts": pairing.iloc[:, white_idx + 2],
        "black_pts": pairing.iloc[:, black_idx - 2],
        "black": pairing.iloc[:, black_idx],
        "black_rtg": pairing.iloc[:, black_idx + 1],
    })

    # Clean player names
    for c in ["white", "black"]:
        df[c] = df[c].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
        # Remove asterisks and markers
        df[c] = df[c].str.replace(r"\s*\*\)?", "", regex=True).str.strip()
        # Convert "LastName, FirstName" to "LastName FirstName"
        df[c] = df[c].str.replace(", ", " ", regex=False)

    for c in ["white_rtg", "black_rtg"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    for c in ["white_pts", "black_pts"]:
        df[c] = df[c].apply(parse_chess_points)

    df["board"] = pd.to_numeric(df["board"], errors="coerce")
    df = df.dropna(subset=["white", "black"]).reset_index(drop=True)
    # Filter out rows where names are "nan" or empty
    df = df[~df["white"].isin(["nan", ""])]
    df = df[~df["black"].isin(["nan", ""])]
    return df


# ----------------------------
# 2) Probability model
# ----------------------------

def elo_expected_score(r_a: float, r_b: float) -> float:
    """Expected score for player A vs B ignoring draws (standard Elo expectation)."""
    return 1.0 / (1.0 + 10 ** (-(r_a - r_b) / 400.0))


def outcome_probs(r_white: float, r_black: float,
                  draw_base: float = 0.35,
                  draw_amp: float = 0.18,
                  draw_scale: float = 220.0) -> Tuple[float, float, float]:
    """
    Returns (P_white_win, P_draw, P_black_win).

    Draw probability increases when ratings are close and is bounded.
    Remaining mass is split according to Elo expectation.
    """
    if not (np.isfinite(r_white) and np.isfinite(r_black)):
        # fallback if rating missing
        r_white, r_black = 2500.0, 2500.0

    d = abs(r_white - r_black)
    p_draw = draw_base + draw_amp * math.exp(-d / draw_scale)
    p_draw = max(0.05, min(0.70, p_draw))

    ew = elo_expected_score(r_white, r_black)
    non_draw = 1.0 - p_draw
    p_white_win = non_draw * ew
    p_black_win = non_draw * (1.0 - ew)
    return p_white_win, p_draw, p_black_win


def sample_result(p_white_win: float, p_draw: float, p_black_win: float, rng: random.Random) -> float:
    """
    Returns white score in {1.0, 0.5, 0.0}.
    """
    u = rng.random()
    if u < p_white_win:
        return 1.0
    if u < p_white_win + p_draw:
        return 0.5
    return 0.0


# ----------------------------
# 3) Swiss pairing approximation (for rounds 11-13)
# ----------------------------

@dataclass(frozen=True)
class Player:
    name: str
    rtg: float


def swiss_pairing_approx(players: List[Player],
                         points: Dict[str, float],
                         already_played: Optional[Dict[Tuple[str, str], bool]] = None
                         ) -> List[Tuple[str, str]]:
    """
    Simplified Swiss pairing:
      - group by score descending
      - within each score group, sort by rating desc
      - pair top half vs bottom half within group
      - if odd in group, float lowest-rated to next lower group
    Does NOT enforce:
      - strict no-repeat
      - color balancing
      - full FIDE floating priorities
    """
    # Group by points
    score_groups: Dict[float, List[Player]] = {}
    for p in players:
        score_groups.setdefault(points[p.name], []).append(p)

    scores_sorted = sorted(score_groups.keys(), reverse=True)

    # Build ordered list with float handling
    pairs: List[Tuple[str, str]] = []
    floater: Optional[Player] = None

    for s in scores_sorted:
        group = score_groups[s]
        # Insert floater at top of this group (common heuristic)
        if floater is not None:
            group = [floater] + group
            floater = None

        group = sorted(group, key=lambda x: x.rtg, reverse=True)

        if len(group) % 2 == 1:
            # float the lowest-rated player down
            floater = group.pop(-1)

        half = len(group) // 2
        top = group[:half]
        bot = group[half:]
        # Pair i-th in top with i-th in bottom
        for a, b in zip(top, bot):
            pairs.append((a.name, b.name))

    # If one player floated all the way down, pair them with a bye-like dummy (ignored here)
    # In real events a bye would be handled; for this event, byes are rare but possible.
    if floater is not None:
        # give floater a "draw" expectation vs field average by pairing with None
        # We'll treat it as a forced draw in simulation.
        pairs.append((floater.name, "__BYE__"))

    return pairs


# ----------------------------
# 4) Simulation core
# ----------------------------

def simulate_tomorrow(n_sims: int = 20000,
                      seed: int = 7,
                      focus_top_n: int = 60,
                      draw_base: float = 0.35,
                      focus_player: str = "Carlsen Magnus") -> pd.DataFrame:
    """
    Runs Monte Carlo simulations for rounds 10-13.
    Uses:
      - actual points after round 9
      - published round 10 pairings (fixed)
      - approximate Swiss pairing for rounds 11-13

    focus_top_n:
      - to keep simulation fast, include top N from round 9 crosstable.
      - This is usually sufficient for winner probability, but you can increase if you want.
    """
    rng = random.Random(seed)

    standings = load_crosstable_after_rd9()
    standings = standings.sort_values(["pts", "rtg"], ascending=[False, False]).head(focus_top_n).reset_index(drop=True)

    # Build player pool
    players = [Player(row["name"], float(row["rtg"])) for _, row in standings.iterrows()]
    name_to_rtg = {p.name: p.rtg for p in players}

    # Initial points after round 9
    base_points = {row["name"]: float(row["pts"]) for _, row in standings.iterrows()}

    # Round 10 pairings (published) - restrict to our player pool
    rd10 = load_round_pairings()
    rd10 = rd10[rd10["white"].isin(name_to_rtg) & rd10["black"].isin(name_to_rtg)].copy()

    # Track results
    out = []

    for sim in range(n_sims):
        points = dict(base_points)
        already_played = {}  # optional if you want to store repeats; not enforced in pairing_approx

        # ---- Round 10: fixed pairings
        for _, g in rd10.iterrows():
            w, b = g["white"], g["black"]
            p_w, p_d, p_b = outcome_probs(name_to_rtg[w], name_to_rtg[b], draw_base=draw_base)
            w_score = sample_result(p_w, p_d, p_b, rng)
            if b != "__BYE__":
                points[w] += w_score
                points[b] += (1.0 - w_score)
                already_played[tuple(sorted((w, b)))] = True

        # ---- Rounds 11-13: approximate Swiss re-pairing each round
        for _round in [11, 12, 13]:
            pairs = swiss_pairing_approx(players, points, already_played)
            for w, b in pairs:
                if b == "__BYE__":
                    points[w] += 0.5  # forced draw/bye proxy
                    continue
                p_w, p_d, p_b = outcome_probs(name_to_rtg[w], name_to_rtg[b], draw_base=draw_base)
                w_score = sample_result(p_w, p_d, p_b, rng)
                points[w] += w_score
                points[b] += (1.0 - w_score)
                already_played[tuple(sorted((w, b)))] = True

        # Determine winner by points only (tiebreaks ignored)
        max_pts = max(points.values())
        winners = sorted([n for n, p in points.items() if abs(p - max_pts) < 1e-9])
        focus_pts = points.get(focus_player, np.nan)
        out.append({
            "sim": sim,
            "max_pts": max_pts,
            "n_tied": len(winners),
            "focus_pts": focus_pts,
            "focus_is_co_winner_points_only": (focus_player in winners),
            "winner": winners[0] if len(winners) == 1 else "Tie: " + ", ".join(winners[:3]),
        })

    import pandas
    return pandas.DataFrame(out)


def simulate_with_round10_outcome(
    n_sims: int = 10000,
    seed: int = 42,
    focus_top_n: int = 80,
    draw_base: float = 0.37,
    focus_player: str = "Carlsen Magnus"
) -> pd.DataFrame:
    """
    Runs Monte Carlo simulations with explicit tracking of Round 10 outcome.
    Returns detailed results including Round 10 result for the focus player.
    """
    rng = random.Random(seed)

    standings = load_crosstable_after_rd9()
    standings = standings.sort_values(["pts", "rtg"], ascending=[False, False]).head(focus_top_n).reset_index(drop=True)

    # Build player pool
    players = [Player(row["name"], float(row["rtg"])) for _, row in standings.iterrows()]
    name_to_rtg = {p.name: p.rtg for p in players}

    # Initial points after round 9
    base_points = {row["name"]: float(row["pts"]) for _, row in standings.iterrows()}

    # Round 10 pairings (published) - restrict to our player pool
    rd10 = load_round_pairings()
    rd10 = rd10[rd10["white"].isin(name_to_rtg) & rd10["black"].isin(name_to_rtg)].copy()

    # Find focus player's round 10 pairing
    focus_rd10_row = rd10[(rd10["white"] == focus_player) | (rd10["black"] == focus_player)]
    if len(focus_rd10_row) == 0:
        raise ValueError(f"Could not find {focus_player} in Round 10 pairings")

    focus_is_white = focus_rd10_row.iloc[0]["white"] == focus_player
    focus_opponent = focus_rd10_row.iloc[0]["black"] if focus_is_white else focus_rd10_row.iloc[0]["white"]

    out = []

    for sim in range(n_sims):
        points = dict(base_points)
        already_played = {}
        focus_rd10_score = None

        # ---- Round 10: fixed pairings
        for _, g in rd10.iterrows():
            w, b = g["white"], g["black"]
            p_w, p_d, p_b = outcome_probs(name_to_rtg[w], name_to_rtg[b], draw_base=draw_base)
            w_score = sample_result(p_w, p_d, p_b, rng)

            # Track focus player's round 10 result
            if w == focus_player:
                focus_rd10_score = w_score
            elif b == focus_player:
                focus_rd10_score = 1.0 - w_score

            if b != "__BYE__":
                points[w] += w_score
                points[b] += (1.0 - w_score)
                already_played[tuple(sorted((w, b)))] = True

        # ---- Rounds 11-13: approximate Swiss re-pairing each round
        for _round in [11, 12, 13]:
            pairs = swiss_pairing_approx(players, points, already_played)
            for w, b in pairs:
                if b == "__BYE__":
                    points[w] += 0.5
                    continue
                p_w, p_d, p_b = outcome_probs(name_to_rtg[w], name_to_rtg[b], draw_base=draw_base)
                w_score = sample_result(p_w, p_d, p_b, rng)
                points[w] += w_score
                points[b] += (1.0 - w_score)
                already_played[tuple(sorted((w, b)))] = True

        # Determine winner by points only
        max_pts = max(points.values())
        winners = sorted([n for n, p in points.items() if abs(p - max_pts) < 1e-9])
        focus_pts = points.get(focus_player, np.nan)

        # Categorize round 10 outcome
        if focus_rd10_score == 1.0:
            rd10_outcome = "Win"
        elif focus_rd10_score == 0.5:
            rd10_outcome = "Draw"
        else:
            rd10_outcome = "Loss"

        out.append({
            "sim": sim,
            "max_pts": max_pts,
            "n_tied": len(winners),
            "focus_pts": focus_pts,
            "focus_rd10_score": focus_rd10_score,
            "focus_rd10_outcome": rd10_outcome,
            "focus_opponent": focus_opponent,
            "focus_is_co_winner": (focus_player in winners),
            "sole_winner": winners[0] if len(winners) == 1 else None,
        })

    import pandas
    return pandas.DataFrame(out)


def get_top_players_stats(standings_df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Return top N players by points for display."""
    return standings_df.head(n)[["rank", "name", "rtg", "pts"]].copy()


if __name__ == "__main__":
    sims = simulate_tomorrow(
        n_sims=20000,
        seed=42,
        focus_top_n=80,
        draw_base=0.37
    )

    focus_win = sims["focus_is_co_winner_points_only"].mean()
    tie_rate = (sims["n_tied"] > 1).mean()
    print(f"Magnus co-wins on points (tiebreaks ignored): {focus_win:.3%}")
    print(f"Any tie for 1st (points-only):              {tie_rate:.3%}")
    print("\nMagnus final score distribution:")
    print(sims["focus_pts"].value_counts().sort_index())
