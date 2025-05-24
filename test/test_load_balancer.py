#!/usr/bin/env python3
"""
ComeAPI ロードバランサー テストスクリプト
同時リクエストの処理能力と負荷分散の動作確認
"""

import asyncio
import aiohttp
import time
import json
import sys
from typing import List, Dict, Any
import concurrent.futures

class LoadBalancerTester:
    def __init__(self, base_url: str = "http://localhost:9000"):
        self.base_url = base_url
        self.session = None
        
    async def init_session(self):
        """HTTP セッションを初期化"""
        if self.session is None:
            connector = aiohttp.TCPConnector(limit=100)
            timeout = aiohttp.ClientTimeout(total=120)
            self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
    
    async def close_session(self):
        """HTTP セッションを閉じる"""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def test_status(self):
        """ロードバランサーの状態確認"""
        print("🔍 ロードバランサー状態確認...")
        try:
            await self.init_session()
            async with self.session.get(f"{self.base_url}/status") as response:
                if response.status == 200:
                    status = await response.json()
                    print(f"✅ ロードバランサー接続成功")
                    print(f"📊 総バックエンド数: {status['total_backends']}")
                    print(f"🟢 稼働中: {status['healthy_backends']}")
                    return status
                else:
                    print(f"❌ ロードバランサー接続失敗: {response.status}")
                    return None
        except Exception as e:
            print(f"❌ ロードバランサー接続エラー: {e}")
            return None
    
    async def test_models(self):
        """モデル一覧の取得テスト"""
        print("\n📂 モデル一覧取得テスト...")
        try:
            await self.init_session()
            async with self.session.get(f"{self.base_url}/models") as response:
                if response.status == 200:
                    models = await response.json()
                    print(f"✅ モデル一覧取得成功: {len(models['models'])}個")
                    for model in models['models']:
                        print(f"   📄 {model['name']} ({model['size_mb']:.1f}MB)")
                    return models['models']
                else:
                    print(f"❌ モデル一覧取得失敗: {response.status}")
                    return []
        except Exception as e:
            print(f"❌ モデル一覧取得エラー: {e}")
            return []
    
    async def single_generate_request(self, prompt: str, model_name: str, request_id: int) -> Dict[str, Any]:
        """単一の生成リクエスト"""
        start_time = time.time()
        
        request_data = {
            "prompt": prompt,
            "model_name": model_name,
            "max_tokens": 50,
            "temperature": 0.8
        }
        
        try:
            await self.init_session()
            async with self.session.post(f"{self.base_url}/generate", json=request_data) as response:
                end_time = time.time()
                response_time = end_time - start_time
                
                if response.status == 200:
                    result = await response.json()
                    response_text = result['response']
                    return {
                        "request_id": request_id,
                        "success": True,
                        "response_time": response_time,
                        "response_length": len(response_text),
                        "response": response_text[:100] + "..." if len(response_text) > 100 else response_text
                    }
                else:
                    error_text = await response.text()
                    return {
                        "request_id": request_id,
                        "success": False,
                        "response_time": response_time,
                        "error": f"HTTP {response.status}: {error_text}"
                    }
                    
        except Exception as e:
            end_time = time.time()
            response_time = end_time - start_time
            return {
                "request_id": request_id,
                "success": False,
                "response_time": response_time,
                "error": str(e)
            }
    
    async def test_concurrent_requests(self, num_requests: int = 5, model_name: str = None):
        """並行リクエストのテスト"""
        print(f"\n🚀 並行リクエストテスト ({num_requests}個)")
        
        if not model_name:
            models = await self.test_models()
            if not models:
                print("❌ テスト用モデルが見つかりません")
                return
            model_name = models[0]['name']
        
        print(f"📄 使用モデル: {model_name}")
        
        # 異なるプロンプトを準備
        prompts = [
            "Once upon a time in a magical forest,",
            "The future of artificial intelligence is",
            "In a world where technology has advanced,",
            "The secrets of the universe can be found",
            "A young adventurer discovered a hidden",
            "The power of friendship can overcome",
            "In the depths of the ocean lives",
            "The ancient prophecy foretells that",
            "Science has revealed many mysteries, but",
            "The journey of a thousand miles begins"
        ]
        
        start_time = time.time()
        
        # 並行リクエスト実行
        tasks = []
        for i in range(num_requests):
            prompt = prompts[i % len(prompts)]
            task = self.single_generate_request(prompt, model_name, i + 1)
            tasks.append(task)
        
        print("⏳ リクエスト実行中...")
        results = await asyncio.gather(*tasks)
        
        total_time = time.time() - start_time
        
        # 結果分析
        successful = [r for r in results if r['success']]
        failed = [r for r in results if not r['success']]
        
        print(f"\n📊 テスト結果:")
        print(f"   ✅ 成功: {len(successful)}/{num_requests}")
        print(f"   ❌ 失敗: {len(failed)}/{num_requests}")
        print(f"   ⏱️  総実行時間: {total_time:.2f}秒")
        
        if successful:
            avg_response_time = sum(r['response_time'] for r in successful) / len(successful)
            min_response_time = min(r['response_time'] for r in successful)
            max_response_time = max(r['response_time'] for r in successful)
            
            print(f"   📈 平均応答時間: {avg_response_time:.2f}秒")
            print(f"   ⚡ 最速応答: {min_response_time:.2f}秒")
            print(f"   🐌 最遅応答: {max_response_time:.2f}秒")
            
            print(f"\n📝 生成結果例:")
            for i, result in enumerate(successful[:3]):
                print(f"   {i+1}. [{result['response_time']:.2f}s] {result['response']}")
        
        if failed:
            print(f"\n❌ 失敗詳細:")
            for result in failed:
                print(f"   Request {result['request_id']}: {result['error']}")
        
        return results
    
    async def test_sequential_requests(self, num_requests: int = 5, model_name: str = None):
        """逐次リクエストのテスト（比較用）"""
        print(f"\n🔄 逐次リクエストテスト ({num_requests}個)")
        
        if not model_name:
            models = await self.test_models()
            if not models:
                print("❌ テスト用モデルが見つかりません")
                return
            model_name = models[0]['name']
        
        prompts = [
            "Tell me a short story about",
            "Explain the concept of",
            "What would happen if",
            "Describe the importance of",
            "How does technology impact"
        ]
        
        start_time = time.time()
        results = []
        
        for i in range(num_requests):
            prompt = prompts[i % len(prompts)]
            print(f"   📤 Request {i+1}/{num_requests}...")
            result = await self.single_generate_request(prompt, model_name, i + 1)
            results.append(result)
        
        total_time = time.time() - start_time
        
        successful = [r for r in results if r['success']]
        print(f"\n📊 逐次テスト結果:")
        print(f"   ✅ 成功: {len(successful)}/{num_requests}")
        print(f"   ⏱️  総実行時間: {total_time:.2f}秒")
        
        if successful:
            avg_response_time = sum(r['response_time'] for r in successful) / len(successful)
            print(f"   📈 平均応答時間: {avg_response_time:.2f}秒")
        
        return results

async def main():
    if len(sys.argv) > 1:
        base_url = sys.argv[1]
    else:
        base_url = "http://localhost:9000"
    
    num_concurrent = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    
    print("="*60)
    print("🧪 ComeAPI ロードバランサー テストスイート")
    print("="*60)
    print(f"🎯 テスト対象: {base_url}")
    print(f"⚡ 並行リクエスト数: {num_concurrent}")
    print("="*60)
    
    tester = LoadBalancerTester(base_url)
    
    try:
        # 1. 状態確認
        status = await tester.test_status()
        if not status:
            print("❌ ロードバランサーに接続できません")
            return
        
        # 2. モデル一覧確認
        models = await tester.test_models()
        if not models:
            print("❌ モデルが見つかりません")
            return
        
        model_name = models[0]['name']
        
        # 3. 逐次リクエストテスト
        await tester.test_sequential_requests(3, model_name)
        
        # 4. 並行リクエストテスト
        await tester.test_concurrent_requests(num_concurrent, model_name)
        
        print("\n✅ 全テスト完了!")
        
    finally:
        await tester.close_session()

if __name__ == "__main__":
    asyncio.run(main()) 