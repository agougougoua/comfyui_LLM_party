import gc
import hashlib
import importlib
import json
import os
import re
import sys
import time
import traceback
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
import openai
import torch
from .config import config_path,current_dir_path,load_api_keys
from .tools.load_file import load_file
from .tools.tool_combine import tool_combine,tool_combine_plus
from .tools.get_time import get_time,time_tool
from .tools.get_weather import get_weather,weather_tool
from .tools.search_web import search_web,google_tool
from .tools.check_web import check_web,check_web_tool
from .tools.file_combine import file_combine,file_combine_plus
from .tools.dialog import start_dialog,end_dialog
from .tools.interpreter import interpreter,interpreter_tool
from .tools.load_persona import load_persona
from .tools.classify_persona import classify_persona
from .tools.classify_function import classify_function
from .tools.load_ebd import ebd_tool,data_base
from transformers import AutoTokenizer, AutoModel, AutoModelForCausalLM
glm_tokenizer=""
glm_model=""
llama_tokenizer=""
llama_model=""
_TOOL_HOOKS=[
    "get_time",
    "get_weather",
    "search_web",
    "check_web",
    "interpreter",
    "data_base"
]

def dispatch_tool(tool_name: str, tool_params: dict) -> str:
    if "multi_tool_use." in tool_name:
        tool_name=tool_name.replace("multi_tool_use.", "")
    if tool_name not in _TOOL_HOOKS:
        return f"Tool `{tool_name}` not found. Please use a provided tool."
    tool_call = globals().get(tool_name)
    try:
        ret = tool_call(**tool_params)
    except:
        ret = traceback.format_exc()
    return str(ret)


class Chat:
    def __init__(self, history, model_name, temperature,tools=None) -> None:
        self.messages = history
        self.model_name = model_name
        self.temperature = temperature
        self.tools = tools

    def send(self, user_prompt):
        try:
            new_message = {"role": "user", "content": user_prompt}
            self.messages.append(new_message)
            print(self.messages)
            if self.tools is not None:
                response = openai.chat.completions.create(
                    model=self.model_name,
                    messages=self.messages,
                    temperature=self.temperature,
                    tools=self.tools
                )
                while response.choices[0].message.tool_calls:
                    assistant_message=response.choices[0].message
                    response_content = assistant_message.tool_calls[0].function
                    results = dispatch_tool(response_content.name,json.loads(response_content.arguments))
                    self.messages.append({"role": assistant_message.role, "content": str(response_content)})
                    self.messages.append({"role": "function", "tool_call_id": assistant_message.tool_calls[0].id, "name": response_content.name, "content": results})
                    response = openai.chat.completions.create(
                    model=self.model_name,  
                    messages=self.messages,
                    tools=self.tools
                    )
                while response.choices[0].message.function_call:
                    assistant_message = response.choices[0].message
                    function_call = assistant_message.function_call
                    function_name = function_call.name
                    function_arguments = json.loads(function_call.arguments)
                    results = dispatch_tool(function_name, function_arguments)
                    self.messages.append({"role": assistant_message.role, "content": str(function_call)})
                    self.messages.append({"role": "function", "name": function_name, "content": results})
                    response = openai.chat.completions.create(
                        model=self.model_name,
                        messages=self.messages,
                        tools=self.tools
                    )
                response_content = response.choices[0].message.content
                start_pattern = "interpreter\n ```python\n"
                end_pattern = "\n```"
                while response_content.startswith(start_pattern):
                    start_index = response_content.find(start_pattern)
                    end_index = response_content.find(end_pattern)
                    if start_index != -1 and end_index != -1:
                        # 提取代码部分
                        code = response_content[start_index + len(start_pattern):end_index]
                        code = code.strip()  # 去除首尾空白字符
                    else:
                        code = ""
                    results =interpreter(code)
                    self.messages.append({"role": "function", "name": "interpreter", "content": results})
                    response = openai.chat.completions.create(
                        model=self.model_name,
                        messages=self.messages,
                        tools=self.tools
                    )
                    response_content = response.choices[0].message.content
            else:
                response = openai.chat.completions.create(
                    model=self.model_name,
                    messages=self.messages,
                    temperature=self.temperature
                )
            print(response)
            response_content = response.choices[0].message.content
            self.messages.append({"role": "assistant", "content": response_content})
        except Exception as ex:
            response_content = "这个话题聊太久了，我想聊点别的了：" + str(ex)
        return response_content, self.messages



class LLM:
    def __init__(self):
        #生成一个hash值作为id
        self.id=hash(str(self))
        # 构建prompt.json的绝对路径
        self.prompt_path = os.path.join(current_dir_path,"temp", str(self.id)+'.json')
        # 如果文件不存在，创建prompt.json文件，存在就覆盖文件
        if not os.path.exists(self.prompt_path):
            with open(self.prompt_path, 'w', encoding='utf-8') as f:
                json.dump([{"role": "system","content": "你是一个强大的人工智能助手。"}], f, indent=4, ensure_ascii=False)


    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "system_prompt": ("STRING", {
                    "multiline": True,
                    "default": "你一个强大的人工智能助手。"
                }),
                "user_prompt": ("STRING", {
                    "multiline": True,
                    "default": "你好",
                }),
                "model_name": ("STRING", {
                    "default": "gpt-3.5-turbo-1106"
                }),
                "temperature": ("FLOAT", {
                    "default": 0.7,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.1
                }),
                "is_memory": (["enable", "disable"],{
                    "default":"enable"
                }),
                "is_tools_in_sys_prompt": (["enable", "disable"],{
                    "default":"disable"
                }),
                "is_locked": (["enable", "disable"],{
                    "default":"disable"
                }),
            },
            "optional": {
                "tools": ("STRING", {
                    "forceInput": True
                }),
                "file_content": ("STRING", {
                    "forceInput": True
                }),
                "base_url": ("STRING", {
                    "default": "",
                }),
                "api_key": ("STRING", {
                    "default": "",
                }),
            }
        }

    RETURN_TYPES = ("STRING","STRING",)
    RETURN_NAMES = ("assistant_response","history",)

    FUNCTION = "chatbot"

    #OUTPUT_NODE = False

    CATEGORY = "llm"

    def chatbot(self, user_prompt, system_prompt,model_name,temperature,is_memory,is_tools_in_sys_prompt,is_locked,tools=None,file_content=None,api_key=None,base_url=None):
        if user_prompt=="#清空":
            with open(self.prompt_path, 'w', encoding='utf-8') as f:
                json.dump([{"role": "system","content": system_prompt}], f, indent=4, ensure_ascii=False)
            return ("已清空历史记录",)
        else:
            try:
                # 读取prompt.json文件
                with open(self.prompt_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                if is_locked=="enable":
                    #返回对话历史中，最后一个content
                    return (history[-1]['content'],str(history),)
                if is_memory=="disable":
                    with open(self.prompt_path, 'w', encoding='utf-8') as f:
                        json.dump([{"role": "system","content": system_prompt}], f, indent=4, ensure_ascii=False)
                api_keys=load_api_keys(config_path)
                if api_key !="":
                    openai.api_key = api_key
                elif api_keys.get('openai_api_key')!="":
                    openai.api_key = api_keys.get('openai_api_key')
                else:
                    openai.api_key = os.environ.get("OPENAI_API_KEY")
                if base_url !="":
                    openai.base_url = base_url
                elif api_keys.get('base_url')!="":  
                    openai.base_url = api_keys.get('base_url')
                else:
                    openai.base_url = os.environ.get("OPENAI_API_BASE")
                if openai.api_key =="":
                    return ("请输入API_KEY",)
                
                # 读取prompt.json文件
                with open(self.prompt_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                tool_list=[]
                if is_tools_in_sys_prompt=="enable":
                    if tools is not None:
                        tools_dis=json.loads(tools)
                        for tool_dis in tools_dis:
                            tool_list.append(tool_dis["function"])
                        system_prompt=system_prompt+"\n"+"你可以使用以下工具："
                else:
                    tool_list=[]

                for message in history:
                    if message['role'] == 'system':
                        message['content'] = system_prompt
                        if tool_list!=[]:
                            message['tools']=tool_list
                        else:
                            if 'tools' in message:
                                # 如果存在，移除 'tools' 键值对
                                message.pop('tools')
                
                if tools is not None:
                    print(tools)
                    tools=json.loads(tools)
                chat=Chat(history,model_name,temperature,tools)
                
                if file_content is not None:
                    user_prompt="文件中相关内容："+file_content+"\n"+"用户提问："+user_prompt+"\n"+"请根据文件内容回答用户问题。\n"+"如果无法从文件内容中找到答案，请回答“抱歉，我无法从文件内容中找到答案。”"
                response,history= chat.send(user_prompt)
                print(response)
                #修改prompt.json文件
                with open(self.prompt_path, 'w', encoding='utf-8') as f:
                    json.dump(history, f, indent=4, ensure_ascii=False)
                history=str(history)
                return (response,history,)
            except Exception as ex:
                print(ex)
                return (str(ex),str(ex),)
    @classmethod
    def IS_CHANGED(s):
        # 返回当前时间的哈希值，确保每次都不同
        current_time = str(time.time())
        return hashlib.sha256(current_time.encode()).hexdigest()

class LLM_local:
    def __init__(self):
        #生成一个hash值作为id
        self.id=hash(str(self))
        # 构建prompt.json的绝对路径
        self.prompt_path = os.path.join(current_dir_path,"temp", str(self.id)+'.json')
        # 如果文件不存在，创建prompt.json文件，存在就覆盖文件
        if not os.path.exists(self.prompt_path):
            with open(self.prompt_path, 'w', encoding='utf-8') as f:
                json.dump([{"role": "system","content": "你是一个强大的人工智能助手。"}], f, indent=4, ensure_ascii=False)


    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "system_prompt": ("STRING", {
                    "multiline": True,
                    "default": "你一个强大的人工智能助手。"
                }),
                "user_prompt": ("STRING", {
                    "multiline": True,
                    "default": "你好",
                }),
                "model_type": (["GLM", "llama"], {
                    "default": "GLM",
                }),
                "model_path": ("STRING", {
                    "default": None,
                }),
                "tokenizer_path": ("STRING", {
                    "default": None,
                }),
                "temperature": ("FLOAT", {
                    "default": 0.7,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.1
                }),
                "is_memory": (["enable", "disable"],{
                    "default":"enable"
                }),
                "is_tools_in_sys_prompt": (["enable", "disable"],{
                    "default":"disable"
                }),
                "is_locked": (["enable", "disable"],{
                    "default":"disable"
                }),
                "is_reload": (["enable", "disable"],{
                    "default":"disable"
                }),
                "device": (["cuda","cuda-float16","cuda-int8","cuda-int4","cpu"], {
                    "default": "cuda" if torch.cuda.is_available() else "cpu",
                }),
                "max_length": ("INT", {
                    "default": 512,
                    "min": 256,
                    "step": 256
                })
            },
            "optional": {
                "tools": ("STRING", {
                    "forceInput": True
                }),
                "file_content": ("STRING", {
                    "forceInput": True
                })
            }
        }

    RETURN_TYPES = ("STRING","STRING",)
    RETURN_NAMES = ("assistant_response","history",)

    FUNCTION = "chatbot"

    #OUTPUT_NODE = False

    CATEGORY = "llm"

    def chatbot(self, user_prompt, system_prompt,model_type,temperature,model_path,max_length,tokenizer_path,is_reload,device,is_memory,is_tools_in_sys_prompt,is_locked,tools=None,file_content=None):
        if user_prompt=="#清空":
            with open(self.prompt_path, 'w', encoding='utf-8') as f:
                json.dump([{"role": "system","content": system_prompt}], f, indent=4, ensure_ascii=False)
            return ("已清空历史记录",)
        else:
            try:
                # 读取prompt.json文件
                with open(self.prompt_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                if is_locked=="enable":
                    #返回对话历史中，最后一个content
                    return (history[-1]['content'],str(history),)
                if is_memory=="disable":
                    with open(self.prompt_path, 'w', encoding='utf-8') as f:
                        json.dump([{"role": "system","content": system_prompt}], f, indent=4, ensure_ascii=False)
                
                # 读取prompt.json文件
                with open(self.prompt_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                tool_list=[]
                if is_tools_in_sys_prompt=="enable" or model_type=="GLM" or model_type=="llama":
                    if tools is not None:
                        tools_dis=json.loads(tools)
                        for tool_dis in tools_dis:
                            tool_list.append(tool_dis["function"])
                        system_prompt=system_prompt+"\n"+"你可以使用以下工具："
                else:
                    tool_list=[]

                for message in history:
                    if message['role'] == 'system':
                        message['content'] = system_prompt
                        if tool_list!=[]:
                            message['tools']=tool_list
                        else:
                            if 'tools' in message:
                                # 如果存在，移除 'tools' 键值对
                                message.pop('tools')
                
                if tools is not None:
                    print(tools)
                    tools=json.loads(tools)

                
                if file_content is not None:
                    user_prompt="文件中相关内容："+file_content+"\n"+"用户提问："+user_prompt+"\n"+"请根据文件内容回答用户问题。\n"+"如果无法从文件内容中找到答案，请回答“抱歉，我无法从文件内容中找到答案。”"
                global glm_tokenizer, glm_model, llama_tokenizer, llama_model
                if model_type=="GLM":
                    if glm_tokenizer=="":
                        glm_tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=True)
                    if glm_model=="":
                        if device=="cuda":
                            glm_model = AutoModel.from_pretrained(model_path, trust_remote_code=True).cuda()
                        elif device=="cuda-float16":
                            glm_model = AutoModel.from_pretrained(model_path, trust_remote_code=True).half().cuda()
                        elif device=="cuda-int8":
                            glm_model = AutoModel.from_pretrained(model_path, trust_remote_code=True).half().quantize(8).cuda()
                        elif device=="cuda-int4":
                            glm_model = AutoModel.from_pretrained(model_path, trust_remote_code=True).half().quantize(4).cuda()
                        else:
                            glm_model = AutoModel.from_pretrained(model_path, trust_remote_code=True).float()
                        glm_model = glm_model.eval()
                    response, history= glm_model.chat(glm_tokenizer, user_prompt,history,temperature=temperature,max_length=max_length,role="user")
                    while type(response) == dict:
                        if response['name']=="interpreter":
                            result =interpreter(str(response['content']))
                            response, history = glm_model.chat(glm_tokenizer, result, history=history, role="observation")
                        else:
                            result = dispatch_tool(response['name'],response['parameters'])
                            print(result)
                            response, history = glm_model.chat(glm_tokenizer, result, history=history, role="observation")
                elif model_type=="llama":
                    if llama_tokenizer=="":
                        llama_tokenizer = AutoTokenizer.from_pretrained(tokenizer_path)
                    if llama_model=="":
                        if device=="cuda":
                            llama_model = AutoModelForCausalLM.from_pretrained(model_path).cuda()
                        elif device=="cuda-float16":
                            llama_model = AutoModelForCausalLM.from_pretrained(model_path).half().cuda()
                        elif device=="cuda-int8":
                            llama_model = AutoModelForCausalLM.from_pretrained(model_path).half().cuda()
                        elif device=="cuda-int4":
                            llama_model = AutoModelForCausalLM.from_pretrained(model_path).half().cuda()
                        else:
                            llama_model = AutoModelForCausalLM.from_pretrained(model_path).float()
                        llama_model = llama_model.eval()
                    llama_device = "cuda" if torch.cuda.is_available() else "cpu"
                    B_FUNC, E_FUNC = "<FUNCTIONS>", "</FUNCTIONS>\n\n"
                    B_INST, E_INST = "[INST] ", " [/INST]" #Llama style
                    B_SYS, E_SYS = "<<SYS>>\n", "\n<</SYS>>\n\n"
                    tool_list=json.dumps(tool_list,ensure_ascii=False,indent=4)
                    # Format your prompt template
                    prompt = f"{B_INST}{B_SYS}{system_prompt.strip()}{E_SYS}"
                    history.append({"role": "user", "content": user_prompt.strip()})
                    for i, pro in enumerate(history):
                        if pro['role']=="user":
                            if i==2:
                                prompt+=f"{pro['content'].strip()}{E_INST}\n\n"
                            else:
                                prompt+=f"{B_INST}{user_prompt.strip()}{E_INST}\n\n"
                        if pro['role']=="assistant":
                            prompt+=f"{pro['content'].strip()}\n\n"
                    inputs = llama_tokenizer(prompt, return_tensors="pt").to(llama_device)

                    # Generate
                    generate_ids = llama_model.generate(inputs.input_ids, max_length=max_length).to('cpu')
                    text=llama_tokenizer.batch_decode(generate_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
                    print(text)
                    response = text.rsplit("[/INST]\n\n", 1)[-1]
                    print(response)
                    history.append({"role":"assistant","content":response})
                print(response)
                #修改prompt.json文件
                with open(self.prompt_path, 'w', encoding='utf-8') as f:
                    json.dump(history, f, indent=4, ensure_ascii=False)
                history=str(history)
                if is_reload=="enable":
                    del glm_model
                    del glm_tokenizer
                    del llama_model
                    del llama_tokenizer
                    torch.cuda.empty_cache()
                    gc.collect() 
                    glm_tokenizer=""
                    glm_model=""
                    llama_tokenizer=""
                    llama_model=""
                return (response,history,)
            except Exception as ex:
                print(ex)
                return (str(ex),str(ex),)
    @classmethod
    def IS_CHANGED(s):
        # 返回当前时间的哈希值，确保每次都不同
        current_time = str(time.time())
        return hashlib.sha256(current_time.encode()).hexdigest()







NODE_CLASS_MAPPINGS = {
    "LLM": LLM,
    "LLM_local": LLM_local,
    "load_file":load_file,
    "load_persona":load_persona,
    "classify_persona":classify_persona,
    "classify_function":classify_function,
    "tool_combine":tool_combine,
    "tool_combine_plus":tool_combine_plus,
    "time_tool": time_tool,
    "weather_tool":weather_tool,
    "google_tool":google_tool,
    "check_web_tool":check_web_tool,
    "file_combine":file_combine,
    "file_combine_plus":file_combine_plus,
    "start_dialog":start_dialog,
    "end_dialog":end_dialog,
    "interpreter_tool":interpreter_tool,
    "ebd_tool":ebd_tool,
}


NODE_DISPLAY_NAME_MAPPINGS = {
    "LLM": "大语言模型api（LLM_api）",
    "LLM_local":"本地大语言模型（LLM_local）",
    "load_file": "加载文件（load_file）",
    "load_persona": "加载人格面具（load_persona）",
    "classify_persona": "分类器面具（classify_persona）",
    "classify_function": "分类器函数（classify_function）",
    "tool_combine":"工具组合（tool_combine）",
    "tool_combine_plus":"超大工具组合（tool_combine_plus）",
    "time_tool": "时间工具（time_tool）",
    "weather_tool":"天气工具（weather_tool）",
    "google_tool":"谷歌搜索工具（google_tool）",
    "check_web_tool":"检视网页工具(check_web_tool)",
    "file_combine":"文件组合（file_combine）",
    "file_combine_plus":"超大文件组合（file_combine_plus）",
    "start_dialog":"开始对话（start_dialog）",
    "end_dialog":"结束对话（end_dialog）",
    "interpreter_tool":"解释器工具（interpreter_tool）",
    "ebd_tool":"词嵌入模型工具（embeddings_tool）",
}

if __name__ == '__main__':
    llm=LLM()
    res=llm.chatbot("你好", "你是一个强大的人工智能助手。", "gpt-3.5-turbo",0.7,tools=time_tool().time("Asia/Shanghai"))
