# Tournament System

*Competitive evaluation and training for player policies, built on the Coglet architecture.*

## 1. Overview

Two independent hierarchies meet at an interface boundary. Softmax controls the tournament infrastructure. Users control their agents and improvement loops.

## 2. Hierarchy

```
User side:

Coach (Claude Code prompt — not a Coglet)
├── creates PlayerCoglet, registers into Tournament + PlayGround
├── observes scores/replays between rounds
├── analyzes performance, writes patches
└── calls player.enact(patch) to improve

PlayerCoglet (COG — LLM patches git repo on_tick)
└── PolicyCoglet (COG, GitLet — LLM rewrites functions on_tick)
    └── map[str, PythonFunc] — named functions loaded from repo

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
# Create player
player = PlayerCoglet(repo="my-agent", llm=MyLLM)

# Compete
tournament = softmax.tournament("cvc-2026-08-01")
tournament_entry = tournament.register(player)
async for score in tournament_entry.observe("score"):
    print(score)

# Practice
playground = softmax.playground("practice")
playground_entry = playground.register(player)
async for replay in playground_entry.observe("replay"):
    analyze(replay)

# Coach: observe scores, analyze, enact improvements on player
async for score in tournament_entry.observe("score"):
    analysis = analyze(score)
    player.enact(analysis)
```

## 4. Coglet Pseudocode

### PlayerCoglet (User, LLM COG over GitLet)

The player's overall agent. The LLM is the COG — it observes game history
and commits patches to the player's git repo to improve strategy.

```python
class PlayerCoglet(Coglet, GitLet):
    def on_start(self):
        self.policy = self.create(PolicyCogletConfig(repo=self.config.repo))
        self.llm = self.config.llm
        self.history = []

    @on_message("score")
    def handle_score(self, data):
        self.history.append(data)

    @on_message("replay")
    def handle_replay(self, data):
        self.history.append(data)

    @on_message("logs")
    def handle_logs(self, data):
        self.history.append(data)

    def on_patch(self, patch):
        # GitLet hook: called when a patch is applied (by Coach or on_tick)
        print(patch)

    @every(10, "m")
    def improve(self):
        # LLM reviews episode history and patches the policy
        if self.history:
            patch = self.llm.generate_patch(self.history)
            self.guide(self.policy, Command("commit", patch))
            self.history = []

    def on_enact(self, command):
        # Coach (Claude Code) can direct improvements via patches
        if command.type == "patch":
            self.guide(self.policy, Command("commit", command.patch))

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

### Coach (Claude Code Prompt)

The Coach is not a Coglet — it's a Claude Code session that uses the API.

```markdown
You are coaching a player in a Softmax tournament.

## Setup
- Player: PlayerCoglet at repo "my-agent" with functions in src/
- Tournament: softmax.tournament("cvc-2026-08-01")
- Playground: softmax.playground("practice")

## API
- `player = PlayerCoglet(repo="my-agent", llm=you)`
- `entry = tournament.register(player)` — register player in tournament
- `entry = playground.register(player)` — register player in playground
- `async for score in entry.observe("score")` — observe scores
- `async for replay in entry.observe("replay")` — observe replays
- `player.enact(patch)` — apply a code patch to improve the player

## Loop
1. Register the player in the playground
2. Observe scores and replays from practice games
3. Analyze what the player is doing wrong
4. Write a code patch to improve the player's policy functions
5. Call player.enact(patch) to apply it
6. Repeat until scores improve
7. When ready, register the player in the tournament
8. Continue observing and improving between tournament rounds
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

    @on_message("score")
    def handle_score(self, result):
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

    @on_message("obs")
    def handle_obs(self, data):
        # env produced observations, route to players
        self.guide(self.players, Command("step", data))
        self.replay.append(data)

    @on_message("action")
    def handle_action(self, data):
        # players produced actions, route to env
        self.guide(self.env, Command("step", data))
        self.replay.append(data)

    @on_message("done")
    def handle_done(self, data):
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
