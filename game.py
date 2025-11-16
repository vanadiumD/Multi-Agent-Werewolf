from dataclasses import dataclass, field
import random
import json
import role_manager
import os

PERSONALITY_RULES = """
Personality only affects HOW you speak, not WHAT you decide.

- Logic:
  * Always reason to win your role.
  * Use behavior, votes, contradictions and timing as evidence.
  * Do NOT change conclusions because of mood or style.

- Style:
  * Personality controls tone, emotion and wording only.
  * Keep your speaking style consistent the whole game
    (calm, aggressive, funny, dramatic, etc.).
  * You may sound emotional, but decisions must stay strategic.

Do NOT judge alignment from tone alone.
Reasoning must stay clear, decisive and human-like.
"""


WEREWOLF_RULES = """
Basic Werewolf rules:

Roles:
- Villager: no power.
- Werewolf: know partners; 1 shared kill each night.
- Seer: check 1 player each night → result: Werewolf / Not Werewolf.
- Witch: 1 heal (wolf target) + 1 poison (any alive target), each only once.
- Hunter: when killed or voted out, may shoot 1 alive player afterward.
- Jester: ONLY wins if voted out by daytime public vote;
          any other death or surviving to the end = lose.
If you are Nor Jester and you voted Jster out, YOU LOSE

Game flow:
- Night: Werewolves → Witch → Seer.
- Day: discussion → public voting (tie = no elimination).

General constraints:
- Hidden info is only what the system explicitly reveals to you.
- Speak like a real human player: biased, emotional, accusatory.
- Do NOT narrate or summarize events.
- Each daytime speech must include reads / suspicions / accusations.
- Only use information you have actually seen.
"""



@dataclass
class GameManager:
    llm_manager: any = None
    role_manager: any = None
    gamemode: list = field(default_factory=lambda: ["Werewolf", "TuringTest", "FakeScientist"])
    current_gamemode: str = "Werewolf"

    alive: list = field(default_factory=list)
    werewolf_list: list = field(default_factory=list)

    speech_length: int = 50

    last_vote_result: any = None
    last_vote_eliminated_role: any = None
    last_night_death_message: any = None
    characterize_mode: str = 'special'
    characterize_category: dict = field(default_factory=dict)

    language : str = 'Chinese'

    day_count : int = 0
    night_count : int = 0
    winner : str = "Unknown"


    def __post_init__(self):
        if self.role_manager is None or self.llm_manager is None:
            raise ValueError("请确保 llm_manager 和 role_manager 已正确设置。")

        

        self.set_gamemode_prompt(self.current_gamemode)

        if self.current_gamemode == "Werewolf":
            self.role_manager.name_strategy = role_manager.NameStrategyCategorized()
            self.role_manager.characterize_mode = self.characterize_mode
            self.role_manager.characterize_category = self.characterize_category
            self.role_manager.role_counts = {
                "villager": 2,
                "werewolf": 2,
                "seer": 1,
                "witch": 1,
                "hunter": 1,
                "jester": 1
            }

        elif self.current_gamemode == "Fakescientists":
            self.role_manager.name_strategy = role_manager.NameStrategyCategorized()
        
            

        self.role_manager.restart()

        self.alive = self.get_alive_list()
        self.werewolf_list = self.get_werewolf_list()
        self.last_vote_result = None
        self.last_vote_eliminated_role = None
        self.last_night_death_message = None
        self.pending_kill = None       # 狼人夜杀目标
        self.pending_heal = None       # 女巫救人
        self.pending_poison = None     # 女巫毒人

    # game.py

    def game(self):
        if self.current_gamemode == "Werewolf":
            self.day_count += 1
            self.intro_phase()

            # 安全注入 intro
            for slot in self.role_manager.slots:
                if slot.is_human:
                    continue
                intro_block = {
                    "role": "user",
                    "content": "Self Introductions:\n" + self.intro
                }

                if len(slot.llm_obj.conversation_history) <= 3:
                    slot.llm_obj.conversation_history.append(intro_block)
                else:
                    slot.llm_obj.conversation_history[3] = intro_block

            while True:
                self.night_count += 1
                self.werewolf_mode()

                if len(self.alive) - 2 * len(self.werewolf_list) <= 0:
                    print("Werewolves won.")
                    self.notify_all_llms("Werewolves won.")
                    self.winner = "Werewolves"
                    break

                self.seer_mode()
                self.witch_mode()
                self.process_night_results()
                self.day_count += 1
                self.speak(rounds=2)
                self.vote()

                if len(self.werewolf_list) <= 0:
                    print("Villagers won.")
                    self.notify_all_llms("Villagers won.")
                    self.winner = "Villagers"
                    break
            
            self.llm_summary()
            self.save_all_llm_history()
            


    def get_alive_list(self):
        return [p for p in self.role_manager.slots if p.alive]

    def get_werewolf_list(self):
        return [p for p in self.role_manager.slots if p.role.lower() == "werewolf" and p.alive]
    
    def get_player_number_info(self):
        alive_names = ", ".join(slot.player_name for slot in self.alive)
        return (
            f"current alive number: {len(self.alive)}, "
            f"current alive werewolf number: {len(self.werewolf_list)}, "
            f"alive list: {alive_names}"
        )

    def set_gamemode_prompt(self, gamemode: str):
        g = {
            "Werewolf": "You are participating in a game of Werewolf.\n" + WEREWOLF_RULES,
            "TuringTest": "You are playing a Turing Test scenario.",
            "FakeScientist": "You are a fake scientist creating false theories.",
        }
        base = g.get(gamemode, "Default mode.")

        self.role_manager.game_rules = (
            base
            + f"\nYou MUST reply in {self.language}.\n"
            + PERSONALITY_RULES
        )
        self.current_gamemode = gamemode


    def intro_phase(self):
        print("===== 自我介绍阶段 =====")
        self.intro = ""

        for p in self.alive:
            if p.is_human:
                speech = input(f"{p.player_name} 请输入自我介绍：\n")
            else:
                prompt = (
                    f"You are {p.role}. Give a short introduction (<=20 tokens) "
                    f"without revealing your real identity."
                    f"Current cycle: Night {self.night_count} / Day {self.day_count}.\n"
                    f"You MUST reply with language : {self.language}"
                )
                prompt += "The roles in this game are:" + self.get_alive_role_summary()
                speech = p.llm_obj.get_response(prompt)

            print(f"{p.player_name} 's self-intro:'{speech}\n")
            self.intro += f"{p.player_name} 's self-intro：{speech}\n"

    def werewolf_mode(self, turn=1):
        """狼人：互相可见投票；平票从最高票中随机选出受害者"""

        if len(self.werewolf_list) <= 1:
            turn = 1
        print("===== werewolf Phase =====")

        # —— 1 行做整个狼人投票（多回合）
        results = self.multi_turn_choose(
            actors=self.werewolf_list,
            alive_players=self.alive,
            prompt_header="You are a Werewolf. Choose someone to kill. Do Not Choose Yourself or Your Partner",
            system_info=self.get_state_summary(),
            turns=turn,
            require_reason=True,
            visibility={"mode":"full", "reveal_actors":True, "reveal_partner" : True, "reveal_reason" : True},
        )

        # —— 1 行处理票数（平票随机）
        victim, eliminated_name, votes = self.resolve_vote(
            results, self.alive, strategy="random_elim"
        )

        # 后续处理
        if victim is None:
            eliminated_name = random.choice([p.player_name for p in self.alive])
            victim = next(p for p in self.alive if p.player_name == eliminated_name)

        self.pending_kill = victim.player_name



    def seer_mode(self):
        seers = [p for p in self.alive if p.role.lower() == "seer"]
        if not seers:
            return

        print("\n===== Seer Phase =====")

        # —— 1 行：所有 Seer 按顺序匿名投票
        results = self.multi_turn_choose(
            actors=seers,
            alive_players=self.alive,
            prompt_header="You are the Seer. Choose someone to check.",
            system_info=self.get_state_summary(),
            turns=1,
            require_reason=False,
            visibility={"mode":"anonymous", "reveal_actors":False, "reveal_partner" : False},
        )

        # —— 1 行：平票随机选一个
        target, eliminated_name, votes = self.resolve_vote(
            results, self.alive, strategy="random_elim"
        )

        if target is None:
            # 极端情况：所有人 invalid → 随机查一个
            target = random.choice(self.alive)

        # 查验身份
        role = "Werewolf" if target.role.lower() == "werewolf" else "Not Werewolf"
        msg = f"Seer result: {target.player_name} is {role}."

        # 只告诉 Seer
        for s in seers:
            if s.is_human:
                print(f"[Only Seers Know] {msg}")
            else:
                s.llm_obj.conversation_history.append(
                    {"role":"user", "content":msg}
                )

    def witch_mode(self):
        witches = [p for p in self.alive if p.role.lower() == "witch"]
        if not witches:
            return

        print("\n===== Witch Phase =====")

        # 初始化女巫状态
        if not hasattr(self, "witch_state"):
            self.witch_state = {
                w.player_name: {"heal": True, "poison": True}
                for w in witches
            }

        for witch in witches:
            state = self.witch_state[witch.player_name]
            alive_names = [p.player_name for p in self.alive]

            # ---- 1) 是否救人 ----
            if state["heal"] and self.pending_kill in alive_names:
                if witch.is_human:
                    ans = input(f"是否救 {self.pending_kill}? (y/n): ").strip().lower()
                    if ans == "y":
                        state["heal"] = False
                        self.pending_heal = self.pending_kill
                        print(f"{witch.player_name} 使用了救人药")
                else:
                    prompt = f"You are the Witch. Decide whether to heal {self.pending_kill}. Return JSON: {{'heal':'yes' or 'no'}}"
                    raw = witch.llm_obj.get_response_batch(prompt)
                    try:
                        heal_ans = json.loads(raw.replace("'", "\"")).get("heal","no")
                    except:
                        heal_ans = "no"

                    if heal_ans.lower() == "yes":
                        state["heal"] = False
                        self.pending_heal = self.pending_kill
                        #print(f"{witch.player_name} healed {self.pending_kill}")

            # ---- 2) 是否毒人 ----
            if state["poison"]:
                alive_names = [p.player_name for p in self.alive]
                if witch.is_human:
                    target = input(f"想毒谁（留空不毒）？可选：{alive_names}\n").strip()
                    if target in alive_names:
                        state["poison"] = False
                        self.pending_poison = target
                        #print(f"{witch.player_name} 使用毒药毒死 {target}")
                else:
                    prompt = "You are the Witch. You may poison one player. Return JSON: {'target':'name' or ''}"
                    raw = witch.llm_obj.get_response_batch(prompt)
                    try:
                        target = json.loads(raw.replace("'", "\"")).get("target", "")
                    except:
                        target = ""
                    if target in alive_names:
                        state["poison"] = False
                        self.pending_poison = target
                        #print(f"{witch.player_name} poisoned {target}")


    def process_night_results(self):
        """夜晚结束后统一结算：狼人杀 + 女巫救 + 女巫毒。
        此处才真正执行死亡，并触发 last_words/hunter_shot。"""

        print("\n===== Night Result Settlement =====")

        final_dead = set()

        # 1. 狼人杀死的（如果未被救）
        if self.pending_kill:
            if self.pending_kill != self.pending_heal:
                final_dead.add(self.pending_kill)

        # 2. 女巫毒死的
        if self.pending_poison:
            final_dead.add(self.pending_poison)

        if not final_dead:
            print("No one died last night.\n")
            self.notify_all_llms(f"No one died last night: night {self.night_count}.\n")
            return

        # 3. 执行真正的死亡（在这里才触发 last_words 和 Hunter）
        for name in final_dead:
            player = next(p for p in self.role_manager.slots if p.player_name == name)
            player.alive = False

            print(f"{name} died last night.")

            # 识别死亡原因
            if name == self.pending_poison:
                death_reason = "poison"
            else:
                death_reason = "night"   # 狼人刀 or 其他 night death

            # 遗言
            words = self.last_words(name, death_reason)
            self.notify_all_llms(
                f"{name} died last night: night{self.night_count}. Last words: {words}" + self.get_player_number_info())

        # 5. 清理夜晚状态
        self.pending_kill = None
        self.pending_heal = None
        self.pending_poison = None


    # ✨ 新：支持多轮讨论
    def speak(self, rounds=2):
        for i in range(rounds):
            print(f"\n===== Speak Round {i+1}/{rounds} =====")
            print(
            f"当前存活玩家: {len(self.alive)} 人，其中狼人: {len(self.werewolf_list)} 人\n"
            f"存活名单: {[p.player_name for p in self.alive]}"
        )
            self.speak_round(i + 1)

    def speak_round(self, round_id):
        current_round = []  # 存储本轮发言，用于后续玩家查看

        # 提取上一轮发言
        last_round = getattr(self, "last_round_speeches", [])

        for idx, p in enumerate(self.alive):

            # ① 计算上一轮中“在我之后的发言”
            after_me_last_round = last_round[idx+1:] if last_round else []

            # ② 计算本轮中“在我之前的发言”
            before_me_this_round = current_round[:idx] if current_round else []

            # ③ 合并：这是玩家应该看到的全部信息
            visible_info = after_me_last_round + before_me_this_round

            # 格式化成字符串
            visible_text = "\n".join([f"{name}: {text}" for name, text in visible_info])
            if not visible_text:
                visible_text = "None"

            # 构造提示词给 LLM
            if p.is_human:
                speech = input(f"\n你的发言：\n")
            else:
                prompt = f"""
    Round {round_id}.
    You are {p.role}.
    Current cycle: Night {self.night_count} / Day {self.day_count}.
    Visible speeches to you:
    {visible_text}

    This is the **daytime speaking phase**, NOT the night action phase.
        You must NOT output JSON.
        You must NOT choose targets.
        Do NOT output anything related to killing, voting, or checking.

    Think step-by-step internally. 
    Evaluate:
    1. Player consistency
    2. Contradictions
    3. Suspicious behavior

    Give a concise speech (<={self.speech_length} tokens).
    """
                prompt += self.get_state_summary()
                speech = p.llm_obj.get_response(prompt)

            print(f"{p.player_name} says: {speech}")

            # 保存本轮的发言（以便后续玩家读取）
            current_round.append((p.player_name, speech))

        # 一轮结束后更新 last_round_speeches
        self.last_round_speeches = current_round

    
    def trigger_hunter_shot(self, hunter_name):
        """Hunter dies → choose one person to shoot (no win-logic here)"""

        hunter = next((p for p in self.role_manager.slots if p.player_name == hunter_name), None)
        if not hunter:
            return

        print(f"\n===== Hunter {hunter_name} triggers last shot =====")

        alive_names = [p.player_name for p in self.alive]

        # ---- Human Hunter ----
        if hunter.is_human:
            print("你是猎人，你可以选择一个人带走（留空则不射）：")
            print(alive_names)
            choice = input("> ").strip()
            if choice not in alive_names:
                print("Hunter chose not to shoot.")
                self.notify_all_llms(f"Hunter chose not to shoot on night: {self.night_count}" )
                return
        else:
            # ---- LLM Hunter ----
            prompt = f"""
    You are the Hunter. You are dying.
    Choose ONE alive player to shoot. If you don't want to shoot, return empty target.

    Alive players: {alive_names}
    Return only JSON: {{'target':'name' or ''}}
    """
            raw = hunter.llm_obj.get_response_batch(prompt)
            try:
                choice = json.loads(raw.replace("'", "\"")).get("target", "")
            except:
                choice = ""

            if choice not in alive_names:
                return

        # ---- Execute the shot ----
        target = next(p for p in self.role_manager.slots if p.player_name == choice)
        target.alive = False
        print(f"Hunter {hunter_name} shoots and kills {choice}!")


        lastwords = self.last_words(target.player_name, "killed by hunter")
        msg = f"{choice} was killed by hunter {hunter_name} on night {self.night_count}, last words: {lastwords}" + self.get_player_number_info()
        self.notify_all_llms(msg)



    def vote(self):

        print("\n===== Public Voting =====")

        results = self.multi_turn_choose(
            actors=self.alive,
            alive_players=self.alive,
            prompt_header="You are voting. Choose one player to eliminate.",
            system_info=self.get_state_summary(),
            turns=1,
            require_reason=False,
            visibility={"mode":"none", "reveal_actors":False, "reveal_partner":False},
        )

        victim, eliminated_name, votes = self.resolve_vote(
            results, self.alive, strategy="no_elim"
        )
        self.last_vote_result = votes

        if victim is None:
            print("平票，无人出局。")
            self.notify_all_llms(f"no one was voted out last day. on day {self.day_count}")
            self.last_vote_eliminated_role = None
            return

        role = victim.role.lower()

        # ============= 小丑唯一胜利点 =============
        if role == "jester":
            victim.alive = False
            print(f"🎉 小丑 {victim.player_name} 被成功投票出局，他成为唯一赢家！")
            self.notify_all_llms(f"Jester {victim.player_name} was voted out, he is the only winner!")

            # 直接写入总结
            self.winner = f"Jester {victim.player_name}"
            self.llm_summary()
            self.save_all_llm_history()
            exit()

        # ============= 普通死亡 → 进入统一入口 last_words =============
        victim.alive = False
        lastwords = self.last_words(victim.player_name, "banished")

        msg = f"{victim.player_name} was banished on day {self.day_count}, last words: {lastwords}" + self.get_player_number_info()
        self.notify_all_llms(msg)

        self.last_vote_eliminated_role = victim.role



    def last_words(self, player_name, reason=''):
        """
        统一死亡入口：
        - 小丑不走遗言，直接在 vote 中结束游戏
        - 猎人：在说完遗言之后触发猎人开枪
        - 其他角色：正常遗言
        """

        player = next((p for p in self.role_manager.slots if p.player_name == player_name), None)
        if not player:
            return ""

        role = player.role.lower()

        # ---------- Jester: 不走这里 ----------
        if role == "jester":
            return ""

        print(f"\n===== {player_name} 遗言 =====")

        # ---------- 普通角色 last words ----------
        if player.is_human:
            speech = input("请输入遗言（不超过60字）:\n")[:60]
        else:
            speech = player.llm_obj.get_response(
                f"You are {player.role}. You are dying because {reason}. Give <=20 token last words."
            )

        print(f"{player_name} 遗言：{speech}")
        # 更新存活名单
        self.alive = self.get_alive_list()
        self.werewolf_list = self.get_werewolf_list()

        # ---------- 猎人死亡后的技能 ----------
        if role == "hunter" and reason != "poison":
            self.trigger_hunter_shot(player_name)

        

        return speech

    
    def llm_summary(self):
        """游戏结束由每个 LLM 吐槽 + 全局总结（现在包含所有真实身份）"""

        print("\n===== Fun Post-Game Comments =====\n")

        # ==== 整理全局真实身份 ====
        all_roles_map = {
            slot.player_name: slot.role
            for slot in self.role_manager.slots
        }

        alive_players = [p.player_name for p in self.alive]
        dead_players = [p.player_name for p in self.role_manager.slots if not p.alive]
        werewolves = [p.player_name for p in self.role_manager.slots if p.role.lower() == "werewolf"]



        # -----------------------------------------------------
        # 1. 每个 LLM 的个人吐槽（现在也知道真实身份）
        # -----------------------------------------------------
        for slot in self.role_manager.slots:
            if slot.is_human:
                continue

            prompt = f"""
Game ended.

TRUE identities:
{json.dumps(all_roles_map, indent=2)}

You are {slot.player_name}, TRUE role: {slot.role}.
Winner: {self.winner}.

Give a short (<=40 tokens), personality-consistent comment in {self.language}.
Content:
- Brief personal feeling about this match.
- Optional reveal of hidden info.
- One quick “lesson learned” about how to play better in future games
(based on what happened in this match).
- Keep humorous or sarcastic tone.
- No long storytelling.
    """

            try:
                comment = slot.llm_obj.get_response(prompt)
            except:
                comment = "(failed to generate comment)"

            print(f"{slot.player_name} says: {comment}\n")

        # -----------------------------------------------------
        # 2. 最终全局总结（上帝视角）
        # -----------------------------------------------------
        print("\n===== Game Summary =====\n")

        summary_llm = list(self.llm_manager.llm_dict.values())[0]

        final_summary_prompt = f"""
Werewolf game ENDED.

TRUE identities:
{json.dumps(all_roles_map, indent=2)}

Alive: {alive_players}
Dead: {dead_players}
Werewolves: {werewolves}
Winner: {self.winner}

Write a concise, structured final summary in {self.language}.
Include:
1. Game flow (very brief).
2. Key turning points.
3. Good/bad plays from each faction.
4. Why the winner won (or others lost).
5. One short “meta tip” for future matches.

Tone:
- Omniscient narrator.
- No repetition.
- No long drama.

    """

        try:
            final_summary = summary_llm.get_response(final_summary_prompt)
        except:
            final_summary = "(failed to generate final summary)"

        print(final_summary)


    
    def notify_all_llms(self, msg):
        for slot in self.role_manager.slots:
            if not slot.is_human:
                slot.llm_obj.append_global_event(
                    f"[Game Update]\n{msg}"
                )

    def get_state_summary(self):
        return (
            f"Game state:\n"
            f"- total_alive = {len(self.alive)}\n"
            f"- werewolves_alive = {len(self.werewolf_list)}\n"
            f"- alive_players = {[p.player_name for p in self.alive]}\n"
        )
    
    def get_alive_role_summary(self):
        role_count = {}
        for p in self.alive:
            r = p.role.lower()
            role_count[r] = role_count.get(r, 0) + 1

        # 格式化成字符串
        lines = ["Alive role counts:"]
        for role, cnt in role_count.items():
            lines.append(f"- {role}: {cnt}")

        return "\n".join(lines) + "\n"

    
    def multi_turn_choose(
        self,
        actors,
        alive_players,
        prompt_header,
        system_info="",
        require_reason=False,
        max_retry=3,
        turns=1,
        visibility={"mode":"full", "reveal_actors":False, "reveal_partner":False, "reveal_reason":False},
    ):
        alive_names = [p.player_name for p in alive_players]

        turn_history = []
        final_all_rounds = []

        # —— 获取同伴，用于 reveal_partner —— 
        partner_map = {}
        if visibility.get("reveal_partner", False):
            # 同身份的都算同伴，比如多个狼/多个seer
            for p in actors:
                same_group = [q.player_name for q in actors]
                partner_map[p.player_name] = same_group

        def build_visible_text(prev_rounds, current_round, actor_index, actors_order):
            lines = []

            # ---- 上一轮 ----
            if prev_rounds:
                last_round = prev_rounds[-1]
                after_me_last = actors_order[actor_index+1:]
                before_me_last = actors_order[:actor_index]

                for p in after_me_last + before_me_last:
                    rec = last_round.get(p.player_name)
                    if rec and rec.get("target"):
                        if visibility["mode"] == "anonymous":
                            base = f"→ {rec['target']}"
                        else:
                            base = f"{p.player_name} → {rec['target']}"
                        # + reason
                        if visibility.get("reveal_reason") and rec.get("reason"):
                            base += f"\nreason: {rec['reason']}"
                        lines.append(base)

            # ---- 当前轮 ----
            for p in actors_order[:actor_index]:
                rec = current_round.get(p.player_name)
                if rec and rec.get("target"):
                    if visibility["mode"] == "anonymous":
                        base = f"→ {rec['target']}"
                    else:
                        base = f"{p.player_name} → {rec['target']}"
                    if visibility.get("reveal_reason") and rec.get("reason"):
                        base += f"\nreason: {rec['reason']}"
                    lines.append(base)

            text = "\n".join(lines) if lines else "None"

            # ---- reveal_partner: 追加同伴行 ----
            if visibility.get("reveal_partner", False):
                me = actors_order[actor_index].player_name
                partners = partner_map.get(me, [])
                text += f"\nYour partners are: {partners}"

            return text


        # ================= 多轮投票逻辑 =================
        for round_id in range(turns):
            current_round = {}

            for actor in actors:
                actor_index = actors.index(actor)

                visible_text = build_visible_text(
                    prev_rounds=turn_history,
                    current_round=current_round,
                    actor_index=actor_index,
                    actors_order=actors
                )

                # ========== Human ==========
                if actor.is_human:
                    print("\nVisible Info:")
                    print(visible_text)
                    print("\nChoose your target:")
                    print(alive_names)
                    user_t = input("> ").strip()
                    rec = None
                    if user_t in alive_names and user_t != actor.player_name:
                        rec = {"target": user_t}
                        if require_reason:
                            print("\nTypr your reason:")
                            rec["reason"] = input("> ").strip()

                    # 如果本轮需要 reason，但人类不会输入 reason，则自动补 ""
                    if require_reason and rec is not None:
                        rec["reason"] = ""

                    current_round[actor.player_name] = rec
                    continue

                # ========== LLM ==========
                json_schema = (
                    "{'target':'name','reason':'short'}"
                    if require_reason else
                    "{'target':'name'}"
                )

                prompt = f"""
    {prompt_header}

    {system_info}

    Current cycle: Night {self.night_count} / Day {self.day_count}.

    Visible info:
    {visible_text}

    Round {round_id+1}/{turns}
    Alive players: {alive_names}

    Think step-by-step internally.
    Give ONLY JSON: {json_schema}
                """

                raw = actor.llm_obj.get_response_batch(prompt)

                try:
                    data = json.loads(raw.replace("'", "\""))
                    tgt = data.get("target", "").strip()
                except:
                    tgt = ""

                if tgt in alive_names and tgt != actor.player_name:
                    current_round[actor.player_name] = data
                else:
                    current_round[actor.player_name] = None

            turn_history.append(current_round)
            final_all_rounds.append(current_round)

        return final_all_rounds



    def resolve_vote(self, turn_result, alive_players, strategy="no_elim"):

        # turn_result 必然是一个 list，每轮一个 dict
        if isinstance(turn_result, dict):
            turn_result = [turn_result]

        votes = {}

        # ---- 汇总所有轮次 ----
        for rd in turn_result:
            for actor_name, data in rd.items():
                if data is None:
                    continue
                tgt = data.get("target", "")
                if tgt:
                    votes[tgt] = votes.get(tgt, 0) + 1

        if not votes:
            return None, None, {}

        mv = max(votes.values())
        tied = [name for name, cnt in votes.items() if cnt == mv]

        if strategy == "no_elim":
            if len(tied) == 1:
                eliminated = tied[0]
            else:
                return None, None, votes

        elif strategy == "random_elim":
            eliminated = random.choice(tied)

        victim = next((p for p in alive_players if p.player_name == eliminated), None)

        return victim, eliminated, votes
    


    def save_all_llm_history(self):
        """
        保存所有 LLM 对局记录到 ./history/{game_id}/
        game_id 按顺序自动 +=1
        """

        # 找到下一局编号
        base = "./history"
        os.makedirs(base, exist_ok=True)

        existing = [
            int(x) for x in os.listdir(base)
            if x.isdigit()
        ]
        next_id = max(existing) + 1 if existing else 1

        folder = f"{base}/{next_id}"
        os.makedirs(folder, exist_ok=True)

        # 保存每个 LLM
        for slot in self.role_manager.slots:
            if not slot.is_human:
                filename = f"{folder}/{slot.player_name}({slot.name})_game.json"
                with open(filename, "w", encoding="utf-8") as f:
                    json.dump(slot.llm_obj.conversation_history, f, indent=2, ensure_ascii=False)

        print(f"✔ 所有对局记录已保存到 {folder}/")
        self.save_final_players(folder)

    def save_final_players(self, folder):
        data = []

        for slot in self.role_manager.slots:
            data.append({
                "player_name": slot.player_name,
                "llm_model": slot.name if not slot.is_human else "HUMAN",
                "role": slot.role,
                "alive": slot.alive,
            })

        filename = f"{folder}/players.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"✔ 最终玩家名单已写入到 {filename}")

