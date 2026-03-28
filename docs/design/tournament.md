# Tournament System

*Competitive evaluation and training for player policies, built on the Coglet architecture.*

## 1. Overview

Two independent hierarchies meet at an interface boundary. Softmax controls the tournament infrastructure. Users control their agents and improvement loops.

## 2. Hierarchy

```
User side:

Coach (COG — improvement loop between rounds)
├── PlayerCoglet (COG — LLM patches git repo on_tick)
│   └── PolicyCoglet (COG, GitLet — LLM rewrites functions on_tick)
│       └── map[str, PythonFunc] — named functions loaded from repo
├── registers into Tournament + PlayGround
├── observes scores/replays between rounds
└── guides PlayerCoglet between rounds

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

## 4. Coglet Pseudocode

### PlayerCoglet (User, LLM COG over GitLet)

The player's overall agent. The LLM is the COG — it observes game history
and commits patches to the player's git repo to improve strategy.

```python
class PlayerCoglet(Coglet, TickLet):
    def on_start(self):
        self.policy = self.create(PolicyCogletConfig(repo=self.config.repo))
        self.llm = self.config.llm
        self.history = []

    def on_message(self, channel, data):
        if channel == "obs":
            self.guide(self.policy, Command("step", data))

        if channel == "action":
            self.transmit("action", data)

        if channel == "score":
            self.history.append(data)

    def on_enact(self, command):
        # COG above (Coach) can direct high-level strategy changes
        if command.type == "strategy":
            patch = self.llm.generate_patch(self.history, command.directive)
            self.guide(self.policy, Command("commit", patch))

    def on_tick(self, elapsed):
        # LLM reviews performance and patches the repo
        if self.should_improve():
            patch = self.llm.generate_patch(self.history)
            self.guide(self.policy, Command("commit", patch))
            self.history = []
```

### PolicyCoglet (User, LLM COG over map[str, PythonFunc])

The policy is a named map of Python functions. The LLM is the COG —
it observes execution traces and rewrites individual functions to improve them.

```python
class PolicyCoglet(Coglet, GitLet, TickLet):
    def on_start(self):
        self.functions: dict[str, Callable] = {}
        self.llm = self.config.llm
        self.traces = []
        self.load_from_repo()

    def load_from_repo(self):
        # load all Python functions from the git repo
        for name, func in self.repo.load_functions().items():
            self.functions[name] = func

    def on_enact(self, command):
        if command.type == "step":
            # execute the policy: call functions by name
            obs = command.data
            action = self.functions["decide"](obs)
            self.transmit("action", action)
            self.traces.append({"obs": obs, "action": action})

        if command.type == "commit":
            # apply patch from PlayerCoglet, reload functions
            self.git_apply(command.patch)
            self.load_from_repo()

    def on_tick(self, elapsed):
        # LLM reviews traces and rewrites individual functions
        if self.traces:
            for name, new_code in self.llm.improve_functions(self.traces, self.functions):
                self.repo.write_function(name, new_code)
            self.git_commit("improve functions")
            self.load_from_repo()
            self.traces = []
```

### Coach (User, COG)

```python
class Coach(Coglet):
    def on_start(self):
        self.policy = self.create(self.policy_config)
        self.arena = self.tournament or self.playground
        self.player = self.arena.register(self.policy_config)

    def on_message(self, channel, result):
        # receives score/replay events from arena
        if channel == "score":
            self.scores.append(result)
            self.transmit("score", result)

        if channel == "round_end":
            improved_weights = self.improve(self.scores)
            self.guide(self.policy, Command("update_weights", improved_weights))
            self.arena.register(self.policy_config)  # re-register with updated policy
            self.transmit("policy", self.policy_config)
            self.scores = []

    def improve(self, scores):
        # pluggable improvement strategy
        ...
```

### TournamentCoglet (Softmax, COG)

```python
class TournamentCoglet(Coglet):
    def on_start(self):
        self.players = []
        self.format = self.config.format  # pluggable: bracket, round-robin, ladder

    def register(self, policy_config):
        self.players.append(policy_config)
        return CogletHandle(observe=["score", "replay", "round_end"])

    def on_tick(self):
        for round in self.format.rounds(self.players):
            matchups = self.format.matchups(round, self.players)

            # parallel games via MulLet
            games = self.create(MulLet(
                n=len(matchups),
                configs=[GameConfig(players=m) for m in matchups]
            ))

            # observe all game results
            async for result in self.observe(games, "score"):
                round_scores.append(result)

            # broadcast round results to all registered players
            for player in self.players:
                self.transmit("score", round_scores)
            self.transmit("round_end", round)
```

### GameCoglet (Softmax, COG)

```python
class GameCoglet(Coglet):
    def on_start(self):
        self.scores = []
        # run N episodes for this matchup
        for i in range(self.config.episodes_per_game):
            episode = self.create(EpisodeConfig(
                players=self.config.players,
                env=self.config.env
            ))

    def on_message(self, channel, result):
        if channel == "score":
            self.scores.append(result)

        if len(self.scores) == self.config.episodes_per_game:
            aggregate = self.aggregate(self.scores)
            self.transmit("score", aggregate)

    def aggregate(self, scores):
        # average, sum, elo update, etc.
        ...
```

### EpisodeCoglet (Softmax, COG)

```python
class EpisodeCoglet(Coglet):
    def on_start(self):
        self.env = self.create(self.config.env)
        self.players = self.create(MulLet(
            n=len(self.config.players),
            configs=self.config.players
        ))
        self.replay = []

        # wire env → players → env
        # env transmits observations, players transmit actions

    def on_message(self, channel, data):
        if channel == "obs":
            # env produced observations, route to players
            self.guide(self.players, Command("step", data))
            self.replay.append(data)

        if channel == "action":
            # players produced actions, route to env
            self.guide(self.env, Command("step", data))
            self.replay.append(data)

        if channel == "done":
            self.transmit("score", data.scores)
            self.transmit("replay", self.replay)
```

### EnvCoglet (Softmax, LET)

```python
class EnvCoglet(Coglet):
    def on_start(self):
        self.env = self.config.make_env()
        obs = self.env.reset()
        self.transmit("obs", obs)

    def on_enact(self, command):
        if command.type == "step":
            obs, rewards, done, info = self.env.step(command.actions)
            self.transmit("obs", obs)
            if done:
                self.transmit("done", Scores(rewards))
```

### MulLet (players)

```python
class PlayerMulLet(MulLet):
    def map(self, event):
        # route per-player observation to correct policy
        return [(player_id, obs) for player_id, obs in event.per_player()]

    def reduce(self, results):
        # collect all player actions into one response
        return Actions({r.player_id: r.action for r in results})
```

## 5. Key Design Points

### Trust Boundary

Softmax owns Tournament, PlayGround, GameCoglet, EpisodeCoglet, EnvCoglet. Policy configs come from external users but run inside Softmax infrastructure. CogletHandles returned to users expose only `observe`.

### Shared Interface

Tournament and PlayGround both support `register(policy_config) → CogletHandle`. Coach can use either or both.

### Round Sync

The round boundary is the key synchronization point. Tournament runs parallel games, collects scores, transmits round results, then waits before starting the next round. Coach uses that window to improve the policy.

### Parallel Execution

Games within a round run in parallel via MulLet over GameCoglets. Players within an episode run in parallel via MulLet over policies.
