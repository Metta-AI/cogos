# Tournament System

*Competitive evaluation and training for player policies, built on the Coglet architecture.*

## 1. Overview

Two independent hierarchies meet at an interface boundary. Softmax controls the tournament infrastructure. Users control their agents and improvement loops.

## 2. Hierarchy

```
User side:

Coach (COG — improvement loop)
├── PlayerPolicy (LET — the policy being improved)
├── registers into Tournament + PlayGround
├── observes scores/replays between rounds
└── guides PlayerPolicy to improve before next round

Softmax side:

TournamentCoglet (COG — pluggable matchmaking format)
└── Round N:
    └── MulLet(GameCoglets) ← parallel games per round
        ├── GameCoglet → EpisodeCoglet → EnvCoglet + MulLet(8 players)
        ├── GameCoglet → ...
        └── ...
    → round scores → notify players → wait → next round

PlayGround (COG — same interface as Tournament, for training)
└── same structure, available anytime
```

## 3. User API

```python
# Compete
tournament = softmax.tournament("cvc-2026-08-01")
t_handle = tournament.register(MyPolicyConfig)
async for score in t_handle.observe("score"):
    print(score)

# Train
playground = softmax.playground("practice")
p_handle = playground.register(MyPolicyConfig)
async for replay in p_handle.observe("replay"):
    analyze(replay)

# Auto-improve
coach = Coach(policy=MyPolicyConfig, playground=playground)
async for policy in coach.observe("policy"):
    print(f"improved: {policy}")

# Compete with coaching
coach = Coach(policy=MyPolicyConfig, tournament=tournament, playground=playground)
async for score in coach.observe("score"):
    print(score)
```

## 4. Coglet Roles

### TournamentCoglet (Softmax, COG)

Holds registered policy configs. Matchmaking logic is pluggable — the format (bracket, round-robin, ladder) is a policy that can be swapped by a parent COG.

Per round: selects matchups, creates a MulLet of GameCoglets for parallel execution, collects round scores, transmits results to all registered handles, waits for ready, starts next round.

### PlayGround (Softmax, COG)

Same `register` interface as Tournament. Used for training and experimentation. A policy doesn't know which one it's in.

### GameCoglet (Softmax, COG)

Receives player configs for one matchup. Runs N EpisodeCoglets. Aggregates scores across episodes. Reports to parent.

### EpisodeCoglet (Softmax, COG)

Creates EnvCoglet + MulLet(8 player configs). Wires env↔players. Starts game. Saves replay and score on completion.

### EnvCoglet (Softmax, LET)

The game world. Talks to one CogletHandle (the MulLet). Steps the game.

### MulLet (players)

Maps per-player observations from env to the correct policy. Reduces all player actions into one step response back to env. Appears as one CogletHandle to EpisodeCoglet.

### Coach (User, COG)

Improvement loop. Registers policy into PlayGround and/or Tournament. Observes scores and replays between rounds. Guides PlayerPolicy to improve. Improvement strategy is pluggable.

### PlayerPolicy (User, LET)

The user's agent. Receives observations via `on_message`, returns actions via `transmit`. Accepts improvement directives from Coach via `on_enact`.

## 5. Data Flow

1. **Coach** registers PlayerPolicy config into Tournament/PlayGround
2. **TournamentCoglet** selects matchups, creates MulLet(GameCoglets) for parallel games
3. **GameCoglet** runs N EpisodeCoglets per matchup
4. **EpisodeCoglet** creates EnvCoglet + MulLet(8 player configs), wires them
5. **EnvCoglet** steps the game, sends observations to MulLet, receives actions
6. **MulLet** routes observations to correct policy, collects actions
7. **EpisodeCoglet** saves replay/score on game end
8. **GameCoglet** aggregates episode scores, reports to TournamentCoglet
9. **TournamentCoglet** collects round scores, transmits to registered handles
10. **Coach** observes scores, guides PlayerPolicy to improve, signals ready
11. **TournamentCoglet** starts next round

## 6. Key Design Points

### Trust Boundary

Softmax owns Tournament, PlayGround, GameCoglet, EpisodeCoglet, EnvCoglet. Policy configs come from external users but run inside Softmax infrastructure. CogletHandles returned to users expose only `observe`.

### Shared Interface

Tournament and PlayGround both support `register(policy_config) → CogletHandle`. Coach can use either or both.

### Round Sync

The round boundary is the key synchronization point. Tournament runs parallel games, collects scores, transmits round results, then waits before starting the next round. Coach uses that window to improve the policy.

### Parallel Execution

Games within a round run in parallel via MulLet over GameCoglets. Players within an episode run in parallel via MulLet over policies.
