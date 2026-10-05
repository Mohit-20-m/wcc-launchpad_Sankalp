"""
Bradley-Terry strength estimation, via the standard iterative MM
(minorize-maximize) algorithm -- sometimes called Zermelo's algorithm,
after the same Zermelo of set-theory fame, who first solved this in
1929 for chess tournament rankings.

WHAT PROBLEM THIS SOLVES: given a pile of "A beat B" results, estimate
a single strength number per item such that the probability of i
beating j is strength_i / (strength_i + strength_j). Sort by strength,
get a ranking. This is the same family of math behind chess/game
rating systems.

REGULARIZATION: the naive algorithm breaks down at the edges -- a
project that has never lost gets pushed toward infinite strength, one
that has never won gets pushed toward zero, and a project with zero
comparisons at all has no strength defined whatsoever. We fix this by
giving every real project one "virtual" win and one virtual loss
against a fixed reference opponent (held at strength 1.0). This keeps
every strength finite and defined, at the honest cost of a small bias
toward "average" for projects with very few real comparisons -- the
same philosophy already used for judges with too little data in
normalization.py.
"""

from collections import defaultdict

VIRTUAL_OPPONENT = "__virtual_average__"


def bradley_terry_strengths(
    project_ids: list[str],
    comparisons: list[tuple[str, str]],
    iterations: int = 200,
) -> dict[str, float]:
    """
    comparisons: list of (winner_id, loser_id) pairs.
    Returns {project_id: strength}, all positive. Higher = better.
    """
    if not project_ids:
        return {}

    wins: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for winner, loser in comparisons:
        wins[winner][loser] += 1

    all_ids = list(project_ids) + [VIRTUAL_OPPONENT]
    strength = {pid: 1.0 for pid in all_ids}

    for pid in project_ids:
        wins[pid][VIRTUAL_OPPONENT] += 1
        wins[VIRTUAL_OPPONENT][pid] += 1

    for _ in range(iterations):
        new_strength = {}
        for i in all_ids:
            numerator = sum(wins[i][j] for j in all_ids if j != i)
            denominator = 0.0
            for j in all_ids:
                if j == i:
                    continue
                games_ij = wins[i][j] + wins[j][i]
                if games_ij == 0:
                    continue
                denominator += games_ij / (strength[i] + strength[j])
            new_strength[i] = (numerator / denominator) if denominator > 0 else strength[i]

        # Re-anchor every iteration so the virtual opponent stays
        # exactly at 1.0 -- otherwise all strengths drift together and
        # only relative order (not the numbers themselves) means
        # anything.
        anchor = new_strength[VIRTUAL_OPPONENT]
        scale = (1.0 / anchor) if anchor > 0 else 1.0
        strength = {k: v * scale for k, v in new_strength.items()}

    strength.pop(VIRTUAL_OPPONENT, None)
    return strength
