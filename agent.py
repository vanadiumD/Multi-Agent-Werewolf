# -*- coding: utf-8 -*-
import os
import sys
from openai import OpenAI
from dotenv import load_dotenv
import json
from datetime import datetime
import time
from config import *
import traceback
# 设置标准输出编码为UTF-8
sys.stdout.reconfigure(encoding='utf-8')

class MultiTurnChatAgent:
    def __init__(self, api_key = None, base_url = "", model = "deepseek-r1",stream_mode = True, system_prompt = None):
        """初始化多轮对话代理"""
        if api_key is None:
            load_dotenv()
            self.client = OpenAI(
                api_key=os.getenv("DASHSCOPE_API_KEY"),
                base_url= base_url,
            )
        else:
            self.client = OpenAI(
                api_key=api_key,
                base_url=base_url,
            )
        
        # 初始化对话历史
        if system_prompt:
            self.conversation_history = [{'role': 'system', 'content': system_prompt},
                                         {'role': 'system', 'content': 'Important events are below:\n'}]
        else:
            self.conversation_history = [
                {'role': 'system', 
                'content':  (
                'You must reply in the same language as the user input: '
                'if the user speaks Chinese, reply in Chinese; '
                'if the user speaks English, reply in English.\n'
                '你必须与用户使用相同语言回答：用户用中文就用中文回答，用户用英文就用英文回答。\n\n'
                'You are a helpful assistant. Answering user questions correctly is your highest priority, if you are answring valuable questions, you need to give more than 400 words detailed answer to explain'
            )},
            {'role': 'system', 'content': 'Important events are below:\n'}
            ]
        
        # 配置参数
        self.model = model
        self.max_history_length = MAX_HISTORY_LENGTH # 最大保留的对话轮数
        self.stream_mode = stream_mode # 默认使用流式回复

    def set_system_prompt(self, prompt):
        """设置系统提示语"""
        self.conversation_history[0]['content'] = prompt

    def append_global_event(self, text, max_events=20):
        if len(self.conversation_history) < 2:
            self.conversation_history.append({'role': 'system', 'content': ""})

        # 用 "\n" 保证不会粘在一起
        current = self.conversation_history[1]['content']

        # 分割成事件列表
        events = current.split("\n") if current else []

        # 追加新事件
        events.append(text.strip())

        # 只保留最近 max_events 条
        events = events[-max_events:]

        # 回写
        self.conversation_history[1]['content'] = "\n".join(events)

        
    def add_message(self, role, content):
        """添加消息到对话历史"""
        self.conversation_history.append({
            'role': role,
            'content': content,
            'timestamp': datetime.now().isoformat()
        })
        
        # 保持对话历史在合理长度内（保留system消息）
        if len(self.conversation_history) > self.max_history_length + 1:
            # 保留system消息和最近的对话
            system_msg = self.conversation_history[0]
            event_msg = self.conversation_history[1] if len(self.conversation_history) > 1 else None
            recent_messages = self.conversation_history[2:][-self.max_history_length:]

            self.conversation_history = [system_msg]
            if event_msg:
                self.conversation_history.append(event_msg)
            self.conversation_history += recent_messages

    def get_response_batch(self, user_input):
        """获取AI批量回复（一次性返回完整回复）"""
        try:
            # 添加用户消息到历史
            self.add_message('user', user_input)
            
            # 准备发送给API的消息（不包含timestamp）
            api_messages = [
                {'role': msg['role'], 'content': msg['content']} 
                for msg in self.conversation_history
            ]
            
            # 调用API（非流式）
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=api_messages,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                stream=False,
            )
            
            # 获取回复
            if not hasattr(completion, "choices") or not completion.choices:
                return f"发生错误: API 未返回 choices，请检查模型配置。\n完整返回：{completion}"


            response_content = completion.choices[0].message.content
            if not response_content:
                return f"发生错误: choices[0].message.content 为空。\n完整返回：{completion}"


            
            # 添加AI回复到历史
            self.add_message('assistant', response_content)
            
            return response_content
            
        except Exception as e:

            full_stack = traceback.format_exc()
            return f"发生错误: {str(e)}\n\n==== 详细错误堆栈 ====\n{full_stack}"
    
    def get_response_stream(self, user_input):
        """获取AI流式回复（逐字符显示）"""
        try:
            # 添加用户消息到历史
            self.add_message('user', user_input)
            
            # 准备发送给API的消息（不包含timestamp）
            api_messages = [
                {'role': msg['role'], 'content': msg['content']} 
                for msg in self.conversation_history
            ]
            
            # 调用API（流式）
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=api_messages,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                stream=True,
            )
            
            # 收集完整回复内容
            full_response = ""
            
            # 逐块处理流式回复
            for chunk in stream:

                # 过滤掉空包
                if not chunk.choices or len(chunk.choices) == 0:
                    continue

                delta = chunk.choices[0].delta

                # finish_reason 阶段没有 content
                if not getattr(delta, "content", None):
                    continue

                content = delta.content
                full_response += content

            #print()  # 换行
            
            # 添加AI回复到历史
            self.add_message('assistant', full_response)
            
            return full_response
            
        except Exception as e:
            full_stack = traceback.format_exc()
            return f"发生错误: {str(e)}\n\n==== 流式详细堆栈 ====\n{full_stack}"
    
    def get_response(self, user_input):
        """根据当前模式获取AI回复"""
        if self.stream_mode:
            return self.get_response_stream(user_input)
        else:
            return self.get_response_batch(user_input)
    
    def toggle_mode(self):
        """切换回复模式"""
        self.stream_mode = not self.stream_mode
        mode_name = "流式回复" if self.stream_mode else "批量回复"
        print(f"已切换到 {mode_name} 模式")
        return mode_name
    
    def get_current_mode(self):
        """获取当前回复模式"""
        return "流式回复" if self.stream_mode else "批量回复"
    
    def show_history(self):
        """显示对话历史"""
        print("\n=== 对话历史 ===")
        for i, msg in enumerate(self.conversation_history):
            if msg['role'] == 'system':
                continue
            role_name = "用户" if msg['role'] == 'user' else "AI助手"
            timestamp = msg.get('timestamp', '')
            print(f"{i}. [{role_name}] {timestamp}")
            print(f"   {msg['content']}")
            print()
    
    def clear_history(self):
        """清除对话历史（保留system消息）"""
        self.conversation_history = [self.conversation_history[0]]
        print("对话历史已清除！")
    
    def save_conversation(self, filename=None):
        """保存对话到文件"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"conversation_{timestamp}.json"
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.conversation_history, f, ensure_ascii=False, indent=2)
            print(f"对话已保存到: {filename}")
        except Exception as e:
            print(f"保存失败: {str(e)}")
    
    def load_conversation(self, filename):
        """从文件加载对话"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                self.conversation_history = json.load(f)
            print(f"对话已从 {filename} 加载")
        except Exception as e:
            print(f"加载失败: {str(e)}")
