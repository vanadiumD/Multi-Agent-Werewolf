# main.py（扩展版）
import sys
from llm_manager import LLMManager
from role_manager import RoleManager, NameStrategyCategorized
from game import GameManager

# 全局变量，用于设置 LLM 扮演的玩家数量
LLM_PLAYER_NUMBER = None  


def print_menu():
    print("\n========================")
    print("    Werewolf LLM Game   ")
    print("========================")
    print("1. 添加一个 LLM 模型")
    print("2. 查看已加载的 LLM")
    print("3. 删除一个 LLM 模型")
    print("4. 清空所有模型历史记录")
    print("5. 开始游戏")
    print("6. 设置 LLM 扮演的玩家数量")
    print("7. 退出")
    print("========================")


def add_llm_interactive(llm_manager: LLMManager):
    print("\n--- 添加 LLM 模型 ---")
    name = input("模型名称（英文，无空格，例如 qwen、gpt4 等）： ").strip()
    base_url = input("模型 base_url： ").strip()
    model = input("模型名称（model 字段）： ").strip()

    try:
        ok = llm_manager.add_llm(name=name, base_url=base_url, model=model)
        if ok:
            print(f">>> 模型 {name} 添加成功！")
            llm_manager.save_configs()
        else:
            print(f">>> 模型 {name} 添加失败，请检查 API key 或网络。")
    except Exception as e:
        print(f">>> 添加失败：{e}")


def remove_llm_interactive(llm_manager: LLMManager):
    print("\n--- 删除模型 ---")
    print("当前模型：", list(llm_manager.llm_dict.keys()))
    name = input("请输入需要删除的模型名称： ").strip()

    ok = llm_manager.remove_llm(name)
    if ok:
        print(f">>> 模型 {name} 已删除。")
    else:
        print(">>> 删除失败。")


def start_game(llm_manager: LLMManager):

    print("\n--- 开始狼人杀游戏 ---")
    print("\n--- 玩家名称设置 ---")
    mode = input("是否开启自定义玩家名称？(y/n)： ").strip().lower()

    if mode == "y":
        custom_mode = True
        user_name = input("请输入你的玩家名称： ").strip()
    else:
        custom_mode = False
        user_name = "HUMAN_PLACEHOLDER"

    # 清空上一轮历史
    llm_manager.clear_all_history()

    # 初始化 RoleManager
    role_manager = RoleManager(
        llm_manager=llm_manager,
        player_name=user_name,
    )

    # 彻底清空旧内容
    role_manager.slots.clear()
    role_manager.player_number = 0

    # 添加玩家
    role_manager.add_player(user_name, custom_mode=custom_mode)

    print("\n>>> 当前 LLM 玩家数量设置：", 
          LLM_PLAYER_NUMBER if LLM_PLAYER_NUMBER is not None else "默认（每模型一个实例）")

    # 让 LLM 进入槽位：重要修改
    role_manager.add_llm_agents(player_number=LLM_PLAYER_NUMBER)

    # 初始化 GameManager（内部会处理角色分配等）
    game_manager = GameManager(
        llm_manager=llm_manager,
        role_manager=role_manager
    )

    print("\n>>> 游戏开始！")
    print(">>> LLM 将自动扮演其他角色。\n")

    game_manager.game()


def set_llm_player_number():
    global LLM_PLAYER_NUMBER
    print("\n--- 设置 LLM 玩家数量 ---")
    raw = input("请输入 LLM 扮演的 AI 玩家数量（为空表示默认每模型1人）： ").strip()

    if raw == "":
        LLM_PLAYER_NUMBER = None
        print(">>> 已恢复默认模式（每个 LLM 模型扮演 1 位玩家）。")
        return

    try:
        num = int(raw)
        if num <= 0:
            print(">>> 数字必须大于 0。")
            return
        LLM_PLAYER_NUMBER = num
        print(f">>> 已设置 LLM 玩家数量 = {LLM_PLAYER_NUMBER}")
    except:
        print(">>> 输入无效，请输入整数。")


def main():

    llm_manager = LLMManager()

    try:
        llm_manager.load_configs()
        llm_manager.initialize_llms_from_configs()
    except:
        print("尚未找到 llm_configs.json，将使用空模型列表。")

    while True:
        print_menu()
        choice = input("请输入选项：").strip()

        if choice == "1":
            add_llm_interactive(llm_manager)

        elif choice == "2":
            print("\n当前已加载的 LLM：")
            for name in llm_manager.llm_dict.keys():
                print("-", name)

        elif choice == "3":
            remove_llm_interactive(llm_manager)

        elif choice == "4":
            llm_manager.clear_all_history()

        elif choice == "5":
            start_game(llm_manager)

        elif choice == "6":
            set_llm_player_number()

        elif choice == "7":
            print("退出游戏。")
            sys.exit(0)

        else:
            print("无效选项，请重新输入。")


if __name__ == "__main__":
    main()
