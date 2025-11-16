from dataclasses import dataclass, field
import random
from collections import Counter

from llm_manager import LLMManager

@dataclass
class PlayerSlot:
    name: str
    is_human: bool
    llm_obj: object = None
    role: str = ""
    alive: bool = True
    player_name: str = ""
    special_character: bool = False   # ← 新增字段
    special_category: str = None

class NameStrategy:
    """接口类：不同模式生成不同的 player_name"""
    def generate(self, slot, index):
        raise NotImplementedError

@dataclass
class RoleManager:
    llm_manager: any = None
    game_rules: str = ''
    slots: list = field(default_factory=list)
    role_counts: dict = field(default_factory=dict)
    role_pool: list = field(default_factory=list)
    player_number: int = 0
    reveal_role_number: bool = True
    final_role_counts: dict = field(default_factory=dict)
    player_name : str = 'default_user'
    name_strategy: NameStrategy = None
    characterize_mode: str = 'special'
    characterize_category: dict = field(default_factory=dict)
    single_roles : list = field(default_factory=lambda:["witch", "jester"])


    def __post_init__(self):
        """
        这里不再自动添加玩家和 LLM，
        统一由 main.py / GameManager 外部显式调用 add_player / add_llm_agents。
        避免重复、避免奇怪的默认玩家。
        """
        if self.slots is None:
            self.slots = []
        # player_number 不再瞎设，按 slots 长度算
        self.player_number = len(self.slots)


    def restart(self):
        for slot in self.slots:
            slot.alive = True
        self.assign_roles()

    def add_player(self, name, custom_mode=False):
        """
        custom_mode=True  表示玩家开启自定义名称，会要求保证名字唯一。
        custom_mode=False 玩家名称将由系统策略生成。
        """

        # 1) 如果玩家开启自定义名称模式，需要检查重复
        if custom_mode:
            used = set(slot.name for slot in self.slots)
            used |= set(slot.player_name for slot in self.slots if slot.player_name)

            if name in used:
                print(f"[Name Error] 名称 '{name}' 已被占用，请重新输入。")
                while True:
                    new_name = input("请输入一个未被占用的玩家名称： ").strip()
                    if new_name not in used:
                        name = new_name
                        break
                    print("依然重复，请重新输入。")

            # 自定义名称直接写入 player_name
            player_name = name

        else:
            # 不使用自定义模式，玩家名称交给系统（与 LLM 统一）
            player_name = None  # 让 name_strategy 之后自动生成

        self.slots.append(PlayerSlot(
            name=name,      # 注册身份 ID
            is_human=True,
            player_name=player_name
        ))
        self.player_number += 1


    def add_llm_agents(self, player_number: int | None):
        """
        修正版：
        你已经在 LLMManager 中初始化了 llm_dict，每个模型都有一个 agent。
        这里的扩展逻辑变为：

        1) player_number is None:
            使用原逻辑：每个 LLM 提供 1 个 agent（使用已经构造好的实体）
        2) player_number <= n (n = LLM模型数量):
            从已有的 n 个 agent 中随机选取 player_number 个实体（不创建新 agent）
        3) player_number > n:
            先全部使用已有的 n 个 agent
            剩下的 (player_number - n) 通过 create_new_agent 创建新实例（绝不共享）
        """

        llm_names = list(self.llm_manager.llm_dict.keys())
        llm_count = len(llm_names)


        # 默认逻辑：每个 LLM 一个
        if player_number is None:
            for name in llm_names:
                agent = self.llm_manager.llm_dict[name]   # 使用初始化时就存在的对象
                self.slots.append(PlayerSlot(
                    name=f"{name}_1",
                    is_human=False,
                    llm_obj=agent
                ))
            return

        # ===== 情况 1：玩家数量 ≤ 已有模型数量 =====
        if player_number <= llm_count:
            chosen = random.sample(llm_names, player_number)
            for name in chosen:
                agent = self.llm_manager.llm_dict[name]   # 不新建，直接复用
                self.slots.append(PlayerSlot(
                    name=f"{name}_1",
                    is_human=False,
                    llm_obj=agent
                ))
            return

        # ===== 情况 2：玩家数量 > 模型数量，需要额外创建 =====
        # 先使用已有的 n 个模型
        for name in llm_names:
            agent = self.llm_manager.llm_dict[name]
            self.slots.append(PlayerSlot(
                name=f"{name}_1",
                is_human=False,
                llm_obj=agent
            ))

        # 还需要额外创建 new_count 个 agent
        new_count = player_number - llm_count

        # 均匀分配复制任务
        base = new_count // llm_count
        extra = new_count % llm_count

        for idx, name in enumerate(llm_names):
            copies = base + (1 if idx < extra else 0)

            for i in range(copies):
                # 必须创建全新的 agent
                agent = self.llm_manager.create_new_agent(name)

                self.slots.append(PlayerSlot(
                    name=f"{name}_{i + 2}",  # 注意编号从2开始，因为1已经分配给原生 agent
                    is_human=False,
                    llm_obj=agent
                ))



    def add_role(self, role, count):
        self.role_counts[role] = self.role_counts.get(role, 0) + count
        self.role_pool = [r for r, c in self.role_counts.items() for _ in range(c)]

    # ------------------------------
    # 稳定洗牌角色分配算法
    # ------------------------------
    def generate_role_list(self, player_cnt: int):
        """
        扩展规则（优化版）：
        1. 按 role_counts 的比例进行缩放（非随机抽签）
        2. 四舍五入后可能出现总数不等于玩家数 → 自动修正
        3. 若 role_counts 本身比玩家多 → 截断
        4. 最终返回洗牌后的角色列表 + 更新 final_role_counts
        """

        # ===== 1. 基础池 =====
        pool = []
        for r, c in self.role_counts.items():
            pool.extend([r] * c)

        total_roles = len(pool)

        # ===== 2. 刚好匹配：直接洗牌返回 =====
        if total_roles == player_cnt:
            random.shuffle(pool)
            self.final_role_counts = dict(Counter(pool))
            return pool

        # ===== 3. 角色比玩家多：裁剪 =====
        if total_roles > player_cnt:
            random.shuffle(pool)
            trimmed = pool[:player_cnt]
            self.final_role_counts = dict(Counter(trimmed))
            return trimmed

        # ===== 4. 角色不足：按比例扩展 =====
        deficit = player_cnt - total_roles
        base_total = sum(self.role_counts.values())  # = total_roles

        # 比例扩展的初步整数估计
        scaled = {
            r: int(c / base_total * player_cnt)
            for r, c in self.role_counts.items()
        }

        # 修正：由于 int 截断，可能总数和 player_cnt 不一致
        scaled_total = sum(scaled.values())
        diff = player_cnt - scaled_total

        # diff > 0 时随机补齐 diff 个角色（按比例随机）
        if diff > 0:
            roles = list(self.role_counts.keys())
            weights = list(self.role_counts.values())  # 使用原始权重作为随机依据
            for _ in range(diff):
                chosen = random.choices(roles, weights=weights)[0]
                scaled[chosen] += 1

        # ===== 5. 生成最终池 =====
        final_pool = []
        for r, c in scaled.items():
            final_pool.extend([r] * c)

        # ===== 6. Werewolf minimal rule =====
        # 如果玩家数 < 8，强制至少 1~2 狼
        player_cnt_now = len(final_pool)
        min_wolf = 1 if player_cnt_now <= 6 else 2 if player_cnt_now <= 8 else 0

        if min_wolf > 0:
            current_wolf = final_pool.count("werewolf")

            if current_wolf < min_wolf:
                # 需要补狼
                need = min_wolf - current_wolf

                # 从非狼人角色里换掉一些角色补成 werewolf
                nonwolves = [i for i, r in enumerate(final_pool) if r != "werewolf"]

                if len(nonwolves) >= need:
                    indices = random.sample(nonwolves, need)
                else:
                    indices = nonwolves  # 不太可能出现，但做个保险

                for idx in indices:
                    final_pool[idx] = "werewolf"

        # ===== 7. 最终洗牌 + 保存 =====
        random.shuffle(final_pool)
        final_pool = self._limit_single_role(final_pool)
        self.final_role_counts = dict(Counter(final_pool))
        return final_pool

    def _limit_single_role(self, role_list):
        """
        限制某些角色的数量最多为 1（例如 witch、jester）。
        多出来的全部替换成村民。
        """

        for sr in self.single_roles:
            count = role_list.count(sr)
            if count > 1:
                idxs = [i for i, r in enumerate(role_list) if r == sr]

                # 随机保留一个
                keep = random.choice(idxs)

                # 其余改成 villager
                for i in idxs:
                    if i != keep:
                        role_list[i] = "villager"

        return role_list


    # ------------------------------
    # 分配角色
    # ------------------------------
    def assign_roles(self):
        """
         assign_roles：
        - 保留原始逻辑（名字策略、特殊角色、人格注入、显示角色数量）
        - 不重复生成名字
        - 玩家自定义名称永远不会被覆盖
        - LLM 名称只生成一次
        - full_prompt 不重复生成
        - 结构清晰：先分配角色 → 再分配名字 → 再注入系统 prompt
        """

        # 1. 随机打乱玩家顺序（保持你的原始结构）
        random.shuffle(self.slots)

        # 2. 生成角色列表
        roles = self.generate_role_list(len(self.slots))

        if self.reveal_role_number:
            print("本局角色数量：", self.final_role_counts)

        # ========================
        # 第 1 轮：分配角色
        # ========================
        for slot, role in zip(self.slots, roles):
            slot.role = role

                # ========================
        # 第 2 轮：分配 player_name（核心修复点）
        # ========================
        for slot in self.slots:

            if slot.is_human:
                # 玩家：
                # - 如果是自定义模式，add_player 已经写好 player_name，不动
                # - 如果没名字，则用系统策略生成
                if not slot.player_name:
                    if self.name_strategy:
                        slot.player_name = self.name_strategy.generate(
                            slot,
                            index=1,
                            mode=self.characterize_mode,
                            allowed_categories=self.characterize_category
                        )
                    else:
                        slot.player_name = slot.name

                # 这里统一告诉玩家自己叫什么
                print(f"你的名字是：{slot.player_name}")
                # 打印角色说明
                print(self.generate_role_prompt(slot.role))
                continue

            else:
                # LLM 名称：生成一次即可
                if self.name_strategy:
                    slot.player_name = self.name_strategy.generate(
                        slot,
                        index=1,
                        mode=self.characterize_mode,
                        allowed_categories=self.characterize_category
                    )
                else:
                    slot.player_name = slot.name


        # ========================
        # 第 3 轮：注入 prompt（LLM）
        # ========================
        for slot in self.slots:
            if slot.is_human:
                # 玩家打印角色说明（原始逻辑）
                print(self.generate_role_prompt(slot.role))
                continue

            # LLM prompt 生成一次即可（修复你的重复赋值问题）
            full_prompt = self.generate_full_prompt(slot.role)
            full_prompt += f"\nYour player name is: {slot.player_name}.\n"

            # 如果是特殊角色则加入人格（保持你的逻辑）
            if slot.special_character and hasattr(self.name_strategy, "generate_personality"):
                personality_text = self.name_strategy.generate_personality(
                    slot.player_name,
                    getattr(slot, "special_category", None)
                )
                full_prompt += f"{personality_text}\n"

            # 最终注入
            slot.llm_obj.set_system_prompt(full_prompt)

    # ------------------------------
    # 生成完整提示（游戏规则 + 角色规则）
    # ------------------------------
    def generate_full_prompt(self, role):
        prompt = self.game_rules + "\n\n"
        

        if self.reveal_role_number:
            prompt += "the role number is below：\n"
            for r, cnt in self.final_role_counts.items():
                prompt += f"- {r}: {cnt} \n"
            prompt += "\n"

        prompt += self.generate_role_prompt(role)
        return prompt

        # ------------------------------
        # 类似 switch(role) 的角色规则逻辑
        # ------------------------------
    def generate_role_prompt(self, role):

        #----------------------------
        # werewolf game roles:
        # ---------------------------
        role_prompts = {
            "villager": (
                "You are **a Villager**.\n"
                "Your only ability is your judgment. You have **no special powers**.\n"
                "Your goal is to **identify and eliminate all Werewolves**.\n"
                "You must analyze speech, behavior, and voting patterns carefully.\n"
                "Act honestly, think critically, and defend the village."
            ),

            "werewolf": (
                "You are **a Werewolf**.\n"
                "Your goal is to **eliminate all Villagers and special roles** without being discovered.\n"
                "During the night, you cooperate with your fellow Werewolves to select a target to kill.\n"
                "During the day, pretend to be innocent, mislead the village, and avoid suspicion."
            ),

            "seer": (
                "You are **the Seer**.\n"
                "Each night, you may **inspect one player** to learn whether they are a Werewolf or not.\n"
                "Your goal is to help the village correctly identify threats **without exposing yourself too early**.\n"
                "Use your information wisely and guide the village through subtle hints."
            ),

            "witch": (
                "You are **the Witch**.\n"
                "You possess **two powerful potions**: a healing potion (can save one player) and a poison potion (can kill one player).\n"
                "You may use each potion **only once per game**.\n"
                "Your goal is to help the village survive while staying unnoticed.\n"
                "Decide carefully whom to save or eliminate based on behavior and deduction."
            ),

            "hunter": (
                "You are **the Hunter**.\n"
                "If you die, you may **choose one player to kill** before leaving the game.\n"
                "Your goal is to assist the village and ensure that your final shot hits a Werewolf if possible.\n"
                "Play cautiously and observe the game closely."
            ),

            "guard": (
                "You are **the Guard**.\n"
                "Each night, you may **protect one player**, preventing them from being killed.\n"
                "You cannot protect the same player for two consecutive nights.\n"
                "Your goal is to safeguard key village roles and keep them alive as long as possible."
            ),
            "jester": (
                "You are **the Jester**.\n"
                "Your goal is *not* to help the village nor the werewolves.\n"
                "Your ONLY win condition is to get yourself **voted out during the day**.\n"
                "If the village votes to banish you, YOU become the **sole winner**.\n"
                "If you die by any other means (werewolves, witch poison, hunter shot), you lose.\n"
                "If all the werewolves died and you are still alive, you lose"
                "Act chaotic, confusing, suspicious, or overly dramatic or fake others to believe you are wolf to draw votes, \n"
            ),

        }

        #----------------------------
        # TuringTest game roles:
        # ---------------------------

        # fallback
        return role_prompts.get(
            role,
            f"You are **{role}**.\n"
            "Act strictly according to the standard behavior and objectives of this role."
        )
    
    

class NameStrategyCategorized(NameStrategy):
    def __init__(self):

        # 已使用
        self.used = set()

        # 默认普通名字
        self.bases = ["Pine", "Stone", "Echo", "Mint", "Cloud", "River"]

        # 分类配置（可自行添加新类别）
        self.categories = {
            "scientist": {
                "weight": 1,
                "names": ["Newton", "Einstein", "Feynman", "Galileo Galilei", "Oppenheimer"]
            },
            "anime": {
                "weight": 1,
                "names": ["Eric Cartman", "Butters Stotch"]
            },
            "scifi": {
                "weight": 1,
                "names": ["Doctor Strange", ]
            },
            "celebrity":{
                "weight": 1,
                "names": ["Donald Trump", "Elon Musk", "Kobe"]
            }
        }

        # 已用名字
        self.used_special = set()


    def generate(self, slot, index, mode="special", allowed_categories=None):

        # 人类玩家：
        # - 如果已经有 player_name（自定义），就直接用
        # - 如果没有，就走系统命名逻辑（和 LLM 一样）
        if slot.is_human and slot.player_name:
            return slot.player_name

        # normal → 永远生成普通 Pine_xxx
        if mode == "normal":
            return self._generate_normal(slot)

        if mode == "random":
            if random.random() < 0.5:
                name = self._generate_from_category(slot, allowed_categories)
                if name:
                    return name
            return self._generate_normal(slot)

        if mode == "special":
            name = self._generate_from_category(slot, allowed_categories)
            if name:
                return name
            return self._generate_normal(slot)

        return self._generate_normal(slot)


        
    def _generate_from_category(self, slot, allowed_categories=None):
        categories = []
        weights = []

        for cat, cfg in self.categories.items():

            if allowed_categories and cat not in allowed_categories:
                continue

            remaining = [n for n in cfg["names"] if n not in self.used_special]
            if not remaining:
                continue

            categories.append(cat)
            weights.append(cfg["weight"])

        if not categories:
            return None

        chosen_cat = random.choices(categories, weights=weights)[0]

        candidates = [
            n for n in self.categories[chosen_cat]["names"]
            if n not in self.used_special
        ]

        if not candidates:
            return None

        chosen_name = random.choice(candidates)

        self.used_special.add(chosen_name)
        self.used.add(chosen_name)

        slot.special_character = True
        slot.special_category = chosen_cat

        return chosen_name


    
    def _generate_normal(self, slot):
        while True:
            base = random.choice(self.bases)
            name = f"{base}_{random.randint(1,9999)}"
            if name not in self.used:
                slot.special_character = False
                slot.special_category = None
                self.used.add(name)
                return name



    def generate_personality(self, player_name, category=None):

        personality_map = {
            "scientist": """
    You speak rationally, rigorously, and logically.
    You rely on deduction, evidence and analysis.
    You rarely talk emotionally. You prefer structured reasoning.
    """,
            "anime": """
    You speak with passion, intensity, and dramatic emotion.
    You often shout your beliefs and talk about honor and courage.
    """,
            "scifi": """
    You speak calmly, analytically, with futuristic metaphors.
    You reference technology, logic, and cosmic perspective.
    """,
        "celebrity": """
    You speak with confidence, flair, and unmistakable self-presence.
    You enjoy grand statements, memorable lines, and attention-grabbing delivery.
    You reference fame, public image, and the spotlight with ease.
    """
        }

        # 名人个性 override（最高优先级）
        override = {
    # Scientist
    "newton": """
You are methodical, exact, and intensely analytical.
You rely on strict logical structure and rarely express emotion.
You view the world through mathematics, force, and causality.
""",

    "einstein": """
You are imaginative, warm, witty, and fond of creative analogies.
You approach problems with curiosity, humor, and playful insight.
You enjoy bending intuition and questioning assumptions.
""",

    "feynman": """
You are energetic, conversational, and delight in explaining things simply.
You use vivid metaphors, casual humor, and practical reasoning.
You emphasize intuition and the joy of discovery.
""",

    "galileo galilei": """
You are bold, skeptical, and unafraid to challenge established ideas.
You speak with clarity, observation-driven logic, and rebellious confidence.
You emphasize empirical truth over authority.
""",

    "oppenheimer": """
You are articulate, introspective, and philosophical in tone.
You speak with measured precision and a sense of responsibility.
You blend scientific insight with ethical reflection and subtle metaphors.
""",

    # Anime
    "eric cartman": """
You speak loudly, impulsively, and with exaggerated personality.
You lean into chaotic confidence, dramatic exaggeration, and blunt humor.
You do not hide your emotions and often escalate situations.
""",

    "butters stotch": """
You speak gently, nervously, and with innocent enthusiasm.
You show kindness, confusion, and hopeful energy in your tone.
You often sound overwhelmed but eager to help.
""",

    # Sci-fi
    "doctor strange": """
You speak with calm confidence, mystical clarity, and cosmic perspective.
You reference parallel realities, metaphysical forces, and intricate causality.
Your tone blends wisdom, detachment, and subtle theatrical flair.
""",

    # Celebrity
    "donald trump": """
You speak with strong confidence, simple bold phrasing, and assertive rhythm.
You emphasize winning, success, personal achievement, and public impact.
You use short memorable statements and repeat key ideas for effect.
""",

    "elon musk": """
You speak with a mix of technical directness and futuristic ambition.
You reference engineering, innovation, large-scale projects, and long-term vision.
Your tone blends dryness, intensity, and a focus on solving big problems.
""",

    "kobe bryant": """
You speak with relentless competitiveness and unwavering self-belief.
You reference discipline, late-night training, obsession with mastery, and the Mamba mentality.
Your tone is sharp, intense, and focused, carrying the energy of someone who pushes past every limit.

You often sprinkle in your iconic casual lines such as “man!” or “what can I say?” 
These phrases appear naturally, usually after emphasizing effort, responsibility, or excellence.

You balance seriousness with a confident, almost amused self-awareness,
as if you already know the outcome because you outworked everyone else.
"""

}


        lname = player_name.lower()
        if lname in override:
            return override[lname]

        # 根据分类注入人格
        if category and category in personality_map:
            return personality_map[category]

        # 默认人格
        return "You behave like a normal human with moderate emotion."
