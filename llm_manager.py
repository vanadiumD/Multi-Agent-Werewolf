from dataclasses import dataclass, field
import json
import os
from dotenv import dotenv_values
from agent import MultiTurnChatAgent

@dataclass
class LLMManager:
    llm_dict: dict = field(default_factory=dict)
    configs: dict = field(default_factory=dict)
    length : int = 0

    def add_llm(self, name: str, base_url: str, model: str):
        """
        添加一个新的 LLM，但不包含 API key。
        API key 必须写入 .env，变量名格式： MODELNAME_1_API_KEY
        """
        # 读取 API key，强迫用户把它写进 .env，而不是丢 config 里
        env = dotenv_values(".env")   # 每次调用读取一次文件
        api_key_var = f"{name.upper()}_API_KEY"
        api_key = env.get(api_key_var)
        if api_key is None:
            raise ValueError(f"找不到 {api_key_var}，请把它写进 .env 文件。")

        # 实例化你的 agent
        agent = MultiTurnChatAgent(
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
        # 测试添加的模型是否正常工作
        try:
            resp = agent.get_response("hi")

            # 如果是错误信息（你所有错误都是以 "发生错误:" 开头）
            if isinstance(resp, str) and resp.strip().startswith("发生错误:"):
                print(f"警告：LLM {name} 初始化失败，API 返回错误：{resp}")
                return False

            # 如果 resp 是非空字符串，且不是错误，就认为成功
            if isinstance(resp, str) and len(resp.strip()) > 0:
                print(f"LLM {name} 模型添加成功，测试回复：{resp[:60]}...")
                config = {
                    'base_url': base_url,
                    'model': model,
                }
                agent.clear_history()

                self.configs[name] = config
                self.llm_dict[name] = agent
                self.length += 1
                return True

            # 空内容情况
            print(f"警告：LLM {name} 测试回复为空：{resp}")
            return False

        except Exception as e:
            print(f"警告：LLM {name} 初始化时出现异常：{str(e)}")
            return False

    def remove_llm(self, name):
        if name not in self.llm_dict:
            print(f"模型 {name} 不存在。")
            return False

        self.llm_dict.pop(name)
        self.configs.pop(name, None)
        self.save_configs()
        print(f"模型 {name} 已删除。")
        return True

    def save_configs(self, path="llm_configs.json"):
        """保存 configs 为 JSON。结构为：
           {
             "length": n,
             "model1": {...},
             "model2": {...}
           }
        """
        save_data = {"length": len(self.configs)}
        save_data.update(self.configs)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, indent=4, ensure_ascii=False)

    def load_configs(self, path="llm_configs.json"):
        """加载配置（不包含 API key），并更新 self.configs"""
        if not os.path.exists(path):
            raise FileNotFoundError(f"{path} 不存在。")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 去掉 length 字段
        data.pop("length", None)
        self.configs = data

    def initialize_llms_from_configs(self):
        """根据 self.configs 初始化 llm_dict"""
        self.llm_dict = {}
        self.length = 0
        for name in list(self.configs.keys()):
            config = self.configs[name]
            try:
                passed = self.add_llm(
                    name=name,
                    base_url=config['base_url'],
                    model=config['model']
                )
                if not passed:
                    print(f"初始化 LLM {name} 失败，请检查配置。")
                    ifdelete = input(f"是否从配置中删除 {name}？(y/n): ")
                    if ifdelete.lower() == 'y':
                        self.configs.pop(name)
        
            except Exception as e:
                print(f"初始化 LLM {name} 失败: {str(e)}")
                ifdelete = input(f"是否从配置中删除 {name}？(y/n): ")
                if ifdelete.lower() == 'y':
                    self.configs.pop(name)
        print("初始化成功，当前 LLM 列表：", list(self.configs.keys()))
        self.save_configs()

    def clear_all_history(self):
        "清理所有llm模型的历史"
        for agent in self.llm_dict.values():
            agent.clear_history()
        print("以清理所有llm模型历史")

    def create_new_agent(self, name):
        config = self.configs[name]
        env = dotenv_values(".env")
        api_key_var = f"{name.upper()}_API_KEY"
        api_key = env.get(api_key_var)

        return MultiTurnChatAgent(
            api_key=api_key,
            base_url=config['base_url'],
            model=config['model']
    )

    
        
