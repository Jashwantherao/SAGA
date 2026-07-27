"""Is the generated game actually playable? QA cannot answer that.

QA proves a script compiles and runs without errors. It says nothing about
whether the challenge it encodes is survivable, or whether it applies any
pressure at all. Both failures ship silently: a generated battle passed every
check while running roughly 16 turns against a brief asking for 4-8, and a
depletion level whose drain outpaces every refill compiles perfectly and is
simply unwinnable.

Two things make this checkable without playing:

- the Coder hoists every tuning number into a named variable at the top of the
  script (that is why it does so), which makes them machine-readable; and
- where mechanics are expressed as data rather than code, the rules can be
  re-implemented directly and run thousands of times.

The same precision discipline as the vision gate applies here: only a
definitively broken configuration fails a build. Anything merely tight, or
merely toothless, is reported and left to a human - a false positive spends a
Coder retry on nothing.
"""

import random
import re
import statistics

# A resource level starts full at 100 by convention (the Coder's few-shots
# clamp to 0-100), and drain accelerates as `drain_rate + elapsed * drain_ramp`.
STARTING_RESOURCE = 100.0

# Grace period: how long the player survives from full with no refill at all.
# Below the floor there is no room to reach a refill zone before dying; above
# the ceiling the resource is decorative and the level has no pressure. Both
# bounds are deliberately loose so that only clear-cut cases are flagged.
MIN_GRACE_SECONDS = 6.0
MAX_GRACE_SECONDS = 240.0

DEPLETION_TEMPLATES = {"depletion", "survive_and_deplete"}

# Templates where something actively hunts the player. If the pursuer is at
# least as fast, no route escapes it and the level is unwinnable by
# construction - a check that needs no simulation and no map knowledge.
# capture_zones is excluded on purpose: its patroller follows fixed waypoints
# rather than chasing, so speed parity there is fair.
CHASE_TEMPLATES = {"maze_chase", "dot_maze"}

# Some headroom is needed to actually escape, not merely to not lose ground.
MIN_CHASE_SPEED_MARGIN = 1.05

# Herding is the mirror image: the player chases, so a creature that flees at
# anything close to the player's speed can never be pushed anywhere. Steering
# something needs a lot more margin than merely catching it, because the push
# only works while you are alongside it.
HERD_TEMPLATES = {"herd_to_goal"}
MAX_FLEE_FRACTION = 0.6

# The Coder names these consistently because the few-shots do, but it is free
# to be tolerant - a missed alias only means the check is skipped.
_ALIASES = {
    "drain_rate": ("drain_rate", "drain", "drain_per_sec", "decay_rate"),
    "drain_ramp": ("drain_ramp", "ramp", "drain_acceleration", "ramp_rate"),
    "refill_rate": ("refill_rate", "refill", "recharge_rate"),
    "player_speed": ("speed", "player_speed", "move_speed"),
    # Only the hunting state matters - a "frightened" speed is meant to be slow.
    "pursuer_speed": ("hunter_speed", "chaser_speed", "chase_speed", "enemy_speed",
                      "ghost_speed", "pursuer_speed", "patrol_speed"),
    "flee_speed": ("flee_speed", "creature_speed", "jellyfish_flee_speed",
                   "herd_speed", "critter_speed"),
}

# Tuning numbers arrive as `var speed = 240.0`, `@export var speed: float = 240.0`
# or `const PLAYER_SPEED = 240.0` - the Coder picks freely between them, and a
# pattern that missed `const` silently saw nothing to check on scripts that
# preferred it, reporting them clean without ever looking. A trailing comment is
# common on these lines and must not defeat the match.
_TUNABLE_RE = re.compile(
    r"^\s*(?:@export\s+)?(?:var|const)\s+([A-Za-z_]\w*)\s*(?::\s*\w+\s*)?=\s*"
    r"(-?\d+(?:\.\d+)?)\s*(?:#.*)?$",
    re.MULTILINE,
)


def extract_tunables(script: str) -> dict[str, float]:
    """Pull every top-level numeric constant out of a GDScript file.

    Names are lowercased because constants are conventionally uppercase and the
    alias table is not.
    """
    return {name.lower(): float(value) for name, value in _TUNABLE_RE.findall(script)}


def _lookup(tunables: dict[str, float], key: str) -> float | None:
    for alias in _ALIASES[key]:
        if alias in tunables:
            return tunables[alias]
    return None


def grace_seconds(drain_rate: float, drain_ramp: float) -> float:
    """Seconds to drain from full with no refill.

    Drain at time t is `drain_rate + t * drain_ramp`, so the total drained by
    time T is the integral: drain_rate*T + drain_ramp*T^2/2. Solving that for
    STARTING_RESOURCE gives the survival time in closed form - no simulation
    needed, and no dependence on the level's layout.
    """
    if drain_ramp <= 0:
        return float("inf") if drain_rate <= 0 else STARTING_RESOURCE / drain_rate
    # drain_ramp/2 * T^2 + drain_rate * T - STARTING_RESOURCE = 0
    a, b, c = drain_ramp / 2.0, drain_rate, -STARTING_RESOURCE
    disc = b * b - 4 * a * c
    if disc < 0:  # unreachable for positive inputs, but never crash a build
        return float("inf")
    return (-b + disc**0.5) / (2 * a)


def check_depletion(tunables: dict[str, float]) -> tuple[list[str], list[str]]:
    """Feasibility check for the resource-drain templates."""
    drain_rate = _lookup(tunables, "drain_rate")
    if drain_rate is None:
        return [], []
    drain_ramp = _lookup(tunables, "drain_ramp") or 0.0
    refill_rate = _lookup(tunables, "refill_rate")

    gating, advisory = [], []
    grace = grace_seconds(drain_rate, drain_ramp)

    if grace < MIN_GRACE_SECONDS:
        gating.append(
            f"Balance: the resource drains from full to empty in {grace:.1f}s with no "
            f"refill (drain_rate={drain_rate:g}, drain_ramp={drain_ramp:g}). That is "
            f"too short to reach a refill zone, so the level is unwinnable. Lower the "
            f"drain rate or the ramp so the player survives at least "
            f"{MIN_GRACE_SECONDS:g}s unaided."
        )
    elif grace > MAX_GRACE_SECONDS:
        advisory.append(
            f"Balance (advisory): the resource lasts {grace:.0f}s unaided, so it "
            f"applies almost no pressure."
        )

    # A refill slower than the drain it is meant to counter can never recover
    # the resource, which makes the zones purely decorative.
    if refill_rate is not None and refill_rate <= drain_rate:
        gating.append(
            f"Balance: refill_rate={refill_rate:g} does not exceed drain_rate="
            f"{drain_rate:g}, so standing in a refill zone still loses resource and "
            f"the level cannot be won. Raise refill_rate above the drain rate."
        )
    return gating, advisory


def check_chase(tunables: dict[str, float]) -> tuple[list[str], list[str]]:
    """A pursuer at least as fast as the player cannot be escaped."""
    player = _lookup(tunables, "player_speed")
    pursuer = _lookup(tunables, "pursuer_speed")
    if player is None or pursuer is None or player <= 0:
        return [], []

    if pursuer >= player:
        return [
            f"Balance: the pursuer moves at {pursuer:g} against the player's {player:g}, "
            f"so it can never be outrun and the level is unwinnable. Drop the pursuer "
            f"below {player / MIN_CHASE_SPEED_MARGIN:.0f} to leave escape room."
        ], []
    if pursuer > player / MIN_CHASE_SPEED_MARGIN:
        return [], [
            f"Balance (advisory): the pursuer ({pursuer:g}) is within 5% of the player "
            f"({player:g}) - escapes will depend almost entirely on layout."
        ]
    return [], []


def check_herd(tunables: dict[str, float]) -> tuple[list[str], list[str]]:
    """A creature that flees nearly as fast as the player cannot be steered."""
    player = _lookup(tunables, "player_speed")
    flee = _lookup(tunables, "flee_speed")
    if player is None or flee is None or player <= 0:
        return [], []

    ratio = flee / player
    if ratio > MAX_FLEE_FRACTION:
        return [
            f"Balance: creatures flee at {flee:g} against the player's {player:g} "
            f"({ratio:.0%} of player speed). Herding needs the player to get alongside "
            f"and push, which is impossible above {MAX_FLEE_FRACTION:.0%}. Drop the "
            f"flee speed below {player * MAX_FLEE_FRACTION:.0f}."
        ], []
    return [], []


CHECKED_TEMPLATES = DEPLETION_TEMPLATES | CHASE_TEMPLATES | HERD_TEMPLATES


def check_level(script: str, template: str) -> tuple[list[str], list[str]]:
    """Balance findings for one generated level, split gating vs advisory."""
    tunables = extract_tunables(script)
    if template in DEPLETION_TEMPLATES:
        gating, advisory = check_depletion(tunables)
    elif template in CHASE_TEMPLATES:
        gating, advisory = check_chase(tunables)
    elif template in HERD_TEMPLATES:
        gating, advisory = check_herd(tunables)
    else:
        return [], []

    # A checkable template that yields no findings AND no recognised numbers
    # was not verified - it was skipped. Saying so is the difference between
    # "this level is balanced" and "nothing looked at it", which otherwise read
    # identically in the log.
    if not gating and not advisory and not _lookup(tunables, "player_speed"):
        advisory.append(
            f"Balance (advisory): could not verify {template} - no recognised speed "
            f"tunable found among {sorted(tunables)[:8] or 'nothing parseable'}."
        )
    return gating, advisory


# --------------------------------------------------------------------------
# Data-driven games: when the rules are data, simulate rather than infer.
# --------------------------------------------------------------------------

def simulate_battle(roster: dict, trials: int = 2000) -> dict:
    """Play a turn-based creature battle many times and measure the outcome.

    Expects the roster shape the Designer emits for a battler: types,
    type_chart, moves, creatures, player_party, wild. The player policy is
    optimal-expected-damage, so the win rate is an upper bound on what a
    competent human achieves.
    """
    moves = {m["name"]: m for m in roster["moves"]}
    creatures = {c["name"]: c for c in roster["creatures"]}
    chart = roster["type_chart"]

    def mult(atk_type: str, def_type: str) -> float:
        return chart.get(atk_type, {}).get(def_type, 1.0)

    def damage(atk: dict, dfn: dict, move: dict, spread: bool = True) -> int:
        base = ((2 * atk["level"] / 5 + 2) * move["power"] * atk["attack"] / dfn["defense"]) / 50 + 2
        base *= mult(move["type"], dfn["type"])
        if spread:
            base *= random.uniform(0.85, 1.0)
        return max(1, int(base))

    class Fighter:
        def __init__(self, name: str):
            self.d = creatures[name]
            self.name = name
            self.hp = self.d["max_hp"]
            self.pp = {m: moves[m]["pp"] for m in self.d["moves"]}

        @property
        def alive(self) -> bool:
            return self.hp > 0

        def usable(self) -> list[str]:
            return [m for m in self.d["moves"] if self.pp[m] > 0]

    def best_move(atk: Fighter, dfn: Fighter) -> str | None:
        opts = atk.usable()
        if not opts:
            return None
        return max(opts, key=lambda m: damage(atk.d, dfn.d, moves[m], spread=False)
                   * moves[m]["accuracy"] / 100)

    def one_battle() -> tuple[bool, int]:
        party = [Fighter(n) for n in roster["player_party"]]
        wild = Fighter(roster["wild"])
        active, turns = 0, 0
        while turns < 200:
            turns += 1
            me = party[active]
            if not me.alive:
                nxt = next((i for i, f in enumerate(party) if f.alive), None)
                if nxt is None:
                    return False, turns
                active = nxt
                continue
            my_move = best_move(me, wild)
            wild_move = random.choice(wild.usable()) if wild.usable() else None
            if my_move is None and wild_move is None:
                return False, turns
            order = [(me, wild, my_move), (wild, me, wild_move)]
            if wild.d["speed"] > me.d["speed"]:
                order.reverse()
            for atk, dfn, mv in order:
                if not atk.alive or not dfn.alive or mv is None:
                    continue
                atk.pp[mv] -= 1
                if random.randint(1, 100) > moves[mv]["accuracy"]:
                    continue
                dfn.hp -= damage(atk.d, dfn.d, moves[mv])
                if not dfn.alive:
                    if dfn is wild:
                        return True, turns
                    break
        return False, turns

    results = [one_battle() for _ in range(trials)]
    wins = [t for ok, t in results if ok]
    return {
        "win_rate": len(wins) / len(results),
        "median_turns_to_win": statistics.median(wins) if wins else None,
        "trials": trials,
    }


def check_battle(roster: dict, want_turns: tuple[int, int] = (4, 8)) -> tuple[list[str], list[str]]:
    """Gate an unwinnable battle; report one that is merely the wrong length."""
    result = simulate_battle(roster)
    gating, advisory = [], []
    win_rate, turns = result["win_rate"], result["median_turns_to_win"]

    if win_rate < 0.05:
        gating.append(
            f"Balance: simulated win rate is {win_rate:.0%} over {result['trials']} "
            f"battles with optimal play - this encounter is effectively unwinnable. "
            f"Lower the wild creature's stats or raise the party's."
        )
    elif win_rate > 0.99:
        advisory.append(f"Balance (advisory): win rate {win_rate:.0%} - no challenge.")

    if turns is not None and turns > want_turns[1] * 1.5:
        advisory.append(
            f"Balance (advisory): median {turns:.0f} turns to win against a target of "
            f"{want_turns[0]}-{want_turns[1]} - the wild creature is too tanky."
        )
    return gating, advisory
