# 狼人杀LLM游戏

## 项目介绍
这是一个基于狼人杀规则的命令行游戏，使用Python实现。玩家可以添加多个LLM模型作为AI玩家参与游戏。游戏支持多种角色（狼人、村民、预言家、女巫、猎人、小丑），并包含完整的游戏流程（夜晚行动、白天发言和投票）。游戏可以自定义参与者的角色和性格，比如Kobe，Einstein等。

## 安装指南
1. 克隆仓库：
   ```bash
   git clone https://github.com/your-repo/werewolf-game.git
   cd werewolf-game
   ```
2. 安装依赖：
   ```bash
   pip install -r requirement.txt
   ```

## 配置说明
1. 创建`.env`文件，添加API密钥（示例见`.env.example`）：
   ```env
   QWEN_API_KEY=your_api_key_here
   DEEPSEEK_API_KEY=your_api_key_here
   # 其他模型API密钥...
   ```
   api的名称应该和加入模型的名称的完全大写一致，比如模型是deepseek, .evn文件需要写：
   DEEPSEEK_API_KEY=sk-2222222
3. 修改`llm_configs.json`配置模型参数（可选）

## 运行游戏
```bash
python main.py
```

## 游戏规则概览
- **角色**：狼人、村民、预言家、女巫、猎人、小丑
- **流程**：
  - 夜晚：狼人杀人 → 预言家验人 → 女巫救人/毒人
  - 白天：发言讨论 → 投票出局
- **胜利条件**：
  - 狼人：淘汰所有村民
  - 村民：淘汰所有狼人
  - 小丑：被投票出局


