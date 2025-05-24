"""
ComeAPI - llama-cpp-pythonベースの並列処理APIロジック
"""

import os
import threading
import queue
import time
from typing import Dict, List, Callable, Optional, Any
from llama_cpp import Llama
from concurrent.futures import ThreadPoolExecutor

class Task:
    """処理タスクを表すクラス"""
    def __init__(self, 
                 prompt: str,
                 model_path: str,
                 callback: Callable[[str], None],
                 max_tokens: int = 32768,
                 temperature: float = 0.8,
                 top_k: int = 40,
                 top_p: float = 0.9,
                 client_id: Any = None):
        self.prompt = prompt
        self.model_path = model_path
        self.callback = callback
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_k = top_k
        self.top_p = top_p
        self.client_id = client_id  # クライアント識別用（任意の値）


class TaskQueue:
    """タスクキューを管理するクラス"""
    def __init__(self):
        self.tasks = queue.Queue()
        self.stop_flag = False
        self.lock = threading.Lock()
        
    def push(self, task: Task):
        """タスクをキューに追加"""
        self.tasks.put(task)
        
    def pop(self) -> Optional[Task]:
        """キューからタスクを取得"""
        try:
            return self.tasks.get(block=True, timeout=0.1)
        except queue.Empty:
            return None
    
    def shutdown(self):
        """キューの停止"""
        self.stop_flag = True
    
    def is_empty(self) -> bool:
        """キューが空かどうか"""
        return self.tasks.empty()


class LlamaAPI:
    """LlamaモデルのAPI管理クラス"""
    def __init__(self, num_threads: int = 4):
        self.num_threads = num_threads
        self.task_queue = TaskQueue()
        self.running = False
        self.worker_threads: List[threading.Thread] = []
        self.models_lock = threading.Lock()
        self.loaded_models: Dict[str, Llama] = {}
    
    def start(self, num_workers: int = 4):
        """ワーカースレッドを起動"""
        if self.running:
            return
        
        self.running = True
        
        # ワーカースレッドの作成
        for i in range(num_workers):
            thread = threading.Thread(target=self._worker_function)
            thread.daemon = True
            self.worker_threads.append(thread)
            thread.start()
    
    def shutdown(self):
        """APIの停止"""
        if not self.running:
            return
        
        self.task_queue.shutdown()
        self.running = False
        
        # すべてのワーカースレッドの終了を待つ
        for thread in self.worker_threads:
            if thread.is_alive():
                thread.join()
        
        self.worker_threads.clear()
        
        # ロード済みモデルの解放
        with self.models_lock:
            self.loaded_models.clear()
    
    def _worker_function(self):
        """ワーカースレッドの実行関数"""
        while self.running:
            task = self.task_queue.pop()
            
            if task is None:
                time.sleep(0.01)  # キューが空の場合は少し待機
                continue
                
            self._process_task(task)
            self.task_queue.tasks.task_done()
    
    def _process_task(self, task: Task):
        """タスクの処理"""
        try:
            # モデルの読み込み（キャッシュがあれば再利用）
            model = None
            
            with self.models_lock:
                if task.model_path in self.loaded_models:
                    model = self.loaded_models[task.model_path]
                else:
                    if not os.path.exists(task.model_path):
                        error_msg = f"モデルファイルが見つかりません: {task.model_path}"
                        task.callback(error_msg)
                        return
                    
                    # モデルの読み込み
                    try:
                        model = Llama(
                            model_path=task.model_path,
                            n_ctx=2048,
                            n_threads=self.num_threads
                        )
                        self.loaded_models[task.model_path] = model
                    except Exception as e:
                        error_msg = f"モデルの読み込みに失敗しました: {str(e)}"
                        task.callback(error_msg)
                        return
            
            # テキスト生成
            result = model.create_completion(
                prompt=task.prompt,
                max_tokens=task.max_tokens,
                temperature=task.temperature,
                top_k=task.top_k,
                top_p=task.top_p,
                stream=False
            )
            
            # 結果をコールバックで返す
            generated_text = result["choices"][0]["text"]
            task.callback(generated_text)
            
        except Exception as e:
            error_msg = f"エラーが発生しました: {str(e)}"
            task.callback(error_msg)
    
    def generate(self, 
                prompt: str, 
                model_path: str, 
                callback: Callable[[str], None],
                max_tokens: int = 32768,
                temperature: float = 0.8, 
                top_k: int = 40, 
                top_p: float = 0.9,
                client_id: Any = None):
        """テキスト生成タスクをキューに追加"""
        task = Task(
            prompt=prompt,
            model_path=model_path,
            callback=callback,
            max_tokens=max_tokens,
            temperature=temperature,
            top_k=top_k,
            top_p=top_p,
            client_id=client_id
        )
        
        self.task_queue.push(task)
    
    def is_running(self) -> bool:
        """APIが実行中かどうか"""
        return self.running
    
    def has_pending_tasks(self) -> bool:
        """保留中のタスクがあるかどうか"""
        return not self.task_queue.is_empty()


# シンプルな使用例
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print(f"使用方法: python {sys.argv[0]} <モデルのパス>")
        sys.exit(1)
    
    model_path = sys.argv[1]
    
    # 結果を受け取るコールバック関数
    def print_result(result):
        print("\n結果:")
        print(result)
        print("-" * 50)
    
    # APIの初期化とスタート
    api = LlamaAPI(num_threads=4)
    api.start(num_workers=4)
    
    # テキスト生成のリクエスト
    prompt = "日本の歴史について簡単に説明してください。"
    print(f"プロンプト: {prompt}")
    
    api.generate(
        prompt=prompt,
        model_path=model_path,
        callback=print_result
    )
    
    # すべてのタスクが完了するのを待つ
    while api.has_pending_tasks():
        time.sleep(0.1)
    
    # 少し待ってからシャットダウン
    time.sleep(1)
    api.shutdown() 