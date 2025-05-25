import asyncio
import aiohttp
import time
import sys

class LoadBalancerTester:
    def __init__(self, base_url: str = "http://localhost:9000"):
        self.base_url = base_url
        self.session = None
        
    async def init_session(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()
    
    async def close_session(self):
        if self.session:
            await self.session.close()
    
    async def test_status(self):
        """ステータス確認"""
        print("🔍 ステータス確認...")
        try:
            await self.init_session()
            async with self.session.get(f"{self.base_url}/status") as response:
                if response.status == 200:
                    status = await response.json()
                    print(f"✅ 接続成功 - 稼働中: {status['healthy_backends']}/{status['total_backends']}")
                    return True
                else:
                    print(f"❌ 接続失敗: {response.status}")
                    return False
        except Exception as e:
            print(f"❌ エラー: {e}")
            return False
    
    async def test_models(self):
        """モデル一覧テスト"""
        print("📂 モデル一覧...")
        try:
            await self.init_session()
            async with self.session.get(f"{self.base_url}/v1/models") as response:
                if response.status == 200:
                    models = await response.json()
                    print(f"✅ モデル数: {len(models['data'])}")
                    return models['data'][0]['id'] if models['data'] else None
                else:
                    print(f"❌ 失敗: {response.status}")
                    return None
        except Exception as e:
            print(f"❌ エラー: {e}")
            return None
    
    async def test_chat(self, model_name: str):
        """チャットテスト"""
        print("💬 チャットテスト...")
        try:
            await self.init_session()
            data = {
                "model": model_name,
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 50
            }
            async with self.session.post(f"{self.base_url}/v1/chat/completions", json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    content = result['choices'][0]['message']['content']
                    print(f"✅ 応答: {content[:50]}...")
                    return True
                else:
                    print(f"❌ 失敗: {response.status}")
                    return False
        except Exception as e:
            print(f"❌ エラー: {e}")
            return False
    
    async def test_concurrent(self, model_name: str, num_requests: int = 3):
        """並行テスト"""
        print(f"🚀 並行テスト ({num_requests}個)...")
        
        async def single_request(i):
            data = {
                "model": model_name,
                "messages": [{"role": "user", "content": f"Test {i}"}],
                "max_tokens": 20
            }
            start = time.time()
            async with self.session.post(f"{self.base_url}/v1/chat/completions", json=data) as response:
                elapsed = time.time() - start
                return response.status == 200, elapsed
        
        start_time = time.time()
        results = await asyncio.gather(*[single_request(i) for i in range(num_requests)])
        total_time = time.time() - start_time
        
        successful = sum(1 for success, _ in results if success)
        avg_time = sum(elapsed for _, elapsed in results) / len(results)
        
        print(f"✅ 成功: {successful}/{num_requests}")
        print(f"⏱️ 総時間: {total_time:.2f}s, 平均: {avg_time:.2f}s")
        
        return successful == num_requests

async def main():
    if len(sys.argv) > 1:
        base_url = sys.argv[1]
    else:
        base_url = "http://localhost:9000"
    
    print(f"🧪 ロードバランサーテスト: {base_url}")
    
    tester = LoadBalancerTester(base_url)
    
    try:
        # 基本テスト
        if not await tester.test_status():
            return
        
        model_name = await tester.test_models()
        if not model_name:
            return
        
        if not await tester.test_chat(model_name):
            return
        
        if not await tester.test_concurrent(model_name):
            return
        
        print("\n🎉 全テスト完了")
        
    finally:
        await tester.close_session()

if __name__ == "__main__":
    asyncio.run(main()) 