import os
import sys
import glob
import time
import json
import hashlib
import uuid
import uvicorn
from typing import List, Dict, Any, Optional, Union
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from llama_cpp import Llama

# APIリクエスト用のモデル（OpenAI互換のみ）
# OpenAI API互換のリクエストモデル
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    max_tokens: Optional[int] = Field(default=10000)
    temperature: Optional[float] = Field(default=0.0)
    top_p: Optional[float] = Field(default=0.9)

# Structured Outputs用のリクエストモデル
class StructuredChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    response_format: Optional[Union[Dict[str, Any], BaseModel]] = None
    max_tokens: Optional[int] = Field(default=10000)
    temperature: Optional[float] = Field(default=0.0)
    top_p: Optional[float] = Field(default=0.9)
    seed: Optional[int] = Field(default=0)

# モデル情報レスポンス用のモデル
class ModelInfo(BaseModel):
    name: str
    path: str
    size_mb: float

class ModelsResponse(BaseModel):
    models: List[ModelInfo]

# FastAPIアプリケーションの作成
app = FastAPI(
    title="Backend Server",
    description="ロードバランサー用バックエンドサーバー",
    version="1.0.0"
)

# CORSミドルウェアの設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# グローバル変数
models_dir = ""
llama_model: Optional[Llama] = None
current_model_path = ""

def initialize_server(models_directory: str, num_threads: int):
    global models_dir
    models_dir = models_directory
    
    # モデルディレクトリの確認
    if not os.path.isdir(models_dir):
        raise ValueError(f"モデルディレクトリが存在しません: {models_dir}")
    
    print(f"✅ Backend Server initialized")
    print(f"   📁 Models directory: {models_dir}")
    print(f"   🧵 Threads: {num_threads}")

def load_model(model_path: str, num_threads: int) -> Llama:
    global llama_model, current_model_path
    
    # 既に同じモデルがロードされている場合はそのまま使用
    if llama_model is not None and current_model_path == model_path:
        return llama_model
    
    # 新しいモデルをロード
    print(f"🔄 Loading model: {os.path.basename(model_path)}")
    llama_model = Llama(
        model_path=model_path,
        n_ctx=32768,            # inportant: ここでモデル使用時のmax_contextを調整可能
        n_threads=num_threads,
        verbose=False
    )
    current_model_path = model_path
    print(f"✅ Model loaded successfully")
    return llama_model

# ルート
@app.get("/")
async def root():
    return {"message": "LlamaAPI サーバーが実行中です"}

# OpenAI API互換エンドポイント
@app.get("/v1")
async def v1_root():
    return {
        "object": "api",
        "version": "v1",
        "message": "LlamaAPI Backend Server - OpenAI Compatible"
    }

@app.get("/v1/models")
async def v1_list_models():
    global models_dir
    
    models = []
    model_files = glob.glob(os.path.join(models_dir, "*.gguf"))
    
    for model_path in model_files:
        model_name = os.path.basename(model_path)
        models.append({
            "id": model_name,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "llamaapi",
            "permission": [],
            "root": model_name,
            "parent": None
        })
    
    return {
        "object": "list",
        "data": models
    }

@app.post("/v1/chat/completions")
async def v1_chat_completions(request: ChatCompletionRequest):
    global models_dir
    
    # モデルパスの構築
    model_path = os.path.join(models_dir, request.model)
    
    # モデルの存在確認
    if not os.path.exists(model_path):
        raise HTTPException(status_code=404, detail=f"モデルが見つかりません: {request.model}")
    
    try:
        # メッセージからプロンプトを構築
        prompt = ""
        for msg in request.messages:
            if msg.role == "system":
                prompt += f"System: {msg.content}\n"
            elif msg.role == "user":
                prompt += f"User: {msg.content}\n"
        
        # モデルのロード
        model = load_model(model_path, num_threads=1)
        
        # テキスト生成
        result = model.create_completion(
            prompt=prompt,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
            stream=False
        )
        
        # OpenAI API形式で返却
        return {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request.model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": result["choices"][0]["text"]
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": len(prompt.split()),
                "completion_tokens": len(result["choices"][0]["text"].split()),
                "total_tokens": len(prompt.split()) + len(result["choices"][0]["text"].split())
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成エラー: {str(e)}")

def extract_pydantic_schema(response_format: Union[Dict[str, Any], BaseModel]) -> Dict[str, Any]:
    if isinstance(response_format, dict):
        return response_format
    
    # Pydanticモデルの場合、JSONスキーマを生成
    if hasattr(response_format, 'model_json_schema'):
        schema = response_format.model_json_schema()
        return {
            "type": "json_schema",
            "json_schema": {
                "name": response_format.__name__.lower(),
                "schema": schema
            }
        }
    
    return response_format

def generate_system_fingerprint(model_name: str, seed: int) -> str:
    content = f"{model_name}_{seed}_{int(time.time() // 3600)}"  # 1時間ごとに変わる
    return f"fp_{hashlib.md5(content.encode()).hexdigest()[:12]}"

def estimate_tokens(text: str) -> int:
    return max(1, len(text.split()) + len(text) // 4)

@app.post("/v1/beta/chat/completions/parse")
async def v1_beta_chat_completions_parse(request: StructuredChatCompletionRequest):
    global models_dir
    
    # モデルパスの構築
    model_path = os.path.join(models_dir, request.model)
    
    # モデルの存在確認
    if not os.path.exists(model_path):
        raise HTTPException(status_code=404, detail=f"モデルが見つかりません: {request.model}")
    
    try:
        # メッセージからプロンプトを構築
        prompt = ""
        for msg in request.messages:
            if msg.role == "system":
                prompt += f"System: {msg.content}\n"
            elif msg.role == "user":
                prompt += f"User: {msg.content}\n"
        
        # 構造化出力の指示を追加
        if request.response_format:
            schema_info = extract_pydantic_schema(request.response_format)
            prompt += "\nPlease respond in the following JSON format:\n"
            if isinstance(schema_info, dict) and "json_schema" in schema_info:
                prompt += f"Schema: {json.dumps(schema_info['json_schema']['schema'], indent=2)}\n"
            else:
                prompt += f"{json.dumps(schema_info, indent=2)}\n"
            prompt += "Respond with valid JSON only, no additional text.\n"
        
        # モデルのロード
        model = load_model(model_path, num_threads=1)
        
        # seedを使った再現可能な生成のため、seedを設定
        temperature = request.temperature if request.temperature is not None else 0.0
        
        # テキスト生成
        result = model.create_completion(
            prompt=prompt,
            max_tokens=request.max_tokens,
            temperature=temperature,
            top_p=request.top_p,
            stream=False
        )
        
        generated_content = result["choices"][0]["text"].strip()
        
        # 構造化出力の場合、JSON解析を試行
        parsed_content = None
        if request.response_format:
            try:
                # JSONの開始と終了を見つけて抽出
                json_start = generated_content.find('{')
                json_end = generated_content.rfind('}') + 1
                if json_start != -1 and json_end > json_start:
                    json_str = generated_content[json_start:json_end]
                    parsed_content = json.loads(json_str)
                    # 生成されたJSONを整形して再設定
                    generated_content = json.dumps(parsed_content, ensure_ascii=False, indent=None)
                else:
                    # JSONが見つからない場合は、全体をJSONとして解析を試行
                    parsed_content = json.loads(generated_content)
            except json.JSONDecodeError:
                # JSONパースに失敗した場合は元のテキストを使用
                parsed_content = {"content": generated_content}
                generated_content = json.dumps(parsed_content, ensure_ascii=False)
        
        # トークン数計算
        prompt_tokens = estimate_tokens(prompt)
        completion_tokens = estimate_tokens(generated_content)
        total_tokens = prompt_tokens + completion_tokens
        
        # システムフィンgerprint生成
        system_fingerprint = generate_system_fingerprint(request.model, request.seed or 0)
        
        # OpenAI beta.chat.completions.parse 形式で返却
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        
        # メッセージオブジェクトを構築（model_dump_json対応）
        message_obj = {
            "role": "assistant",
            "content": generated_content,
        }
        
        # 構造化出力の場合、parsed と refusal フィールドを追加
        if request.response_format and parsed_content is not None:
            message_obj["parsed"] = parsed_content
            message_obj["refusal"] = None
        
        response = {
            "id": completion_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request.model,
            "system_fingerprint": system_fingerprint,
            "choices": [
                {
                    "index": 0,
                    "message": message_obj,
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "prompt_tokens_details": {
                    "cached_tokens": 0  # Hawks対応のために追加
                }
            }
        }
        
        return response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成エラー: {str(e)}")

# サーバー起動関数
def start_server(models_directory: str, host: str = "127.0.0.1", port: int = 8080, 
                num_threads: int = 1):
    """バックエンドサーバーを起動"""
    try:
        initialize_server(models_directory, num_threads)
        # CPU使用率を最小化する設定
        uvicorn.run(
            app, 
            host=host, 
            port=port,
            workers=1,              # ワーカー数を1に制限
            loop="asyncio",         # asyncioループを使用
            access_log=False,       # アクセスログを無効化
            log_level="error"       # エラーログのみ出力
        )
    except KeyboardInterrupt:
        print("🛑 Server stopped by user")
    except Exception as e:
        print(f"❌ Server error: {e}")

# メイン実行部分
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"使用方法: python {sys.argv[0]} <モデルディレクトリ> [ホスト=127.0.0.1] [ポート=8080] [スレッド数=1]")
        print(f"例: python {sys.argv[0]} ./models")
        print(f"例: python {sys.argv[0]} ./models 127.0.0.1 8080 1")
        sys.exit(1)
    
    models_directory = sys.argv[1]
    host = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 8080
    num_threads = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    
    print("="*50)
    print("🖥️  Backend Server")
    print("="*50)
    print(f"📁 モデルディレクトリ: {models_directory}")
    print(f"🌐 ホスト: {host}")
    print(f"🔌 ポート: {port}")
    print(f"🧵 スレッド数: {num_threads}")
    print("="*50)
    
    start_server(models_directory, host, port, num_threads) 