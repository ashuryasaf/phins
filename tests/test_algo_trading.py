"""
Test Suite for PHINS Algo Trading System
==========================================
Tests for:
- Trading strategies (Momentum, RSI, MACD, Mean Reversion, etc.)
- Technical indicators (RSI, MACD, Moving Averages, Bollinger Bands)
- Trading bots (create, start, stop, run cycle)
- Order execution and management
- API endpoints
"""

import unittest
import json
import threading
import time
import urllib.request
from http.server import HTTPServer
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAlgoTradingService(unittest.TestCase):
    """Test the algo trading service directly"""
    
    @classmethod
    def setUpClass(cls):
        """Initialize services"""
        from services.algo_trading_service import get_algo_trading_service, TradingStrategy
        from services.investment_portfolio_service import get_portfolio_service
        
        cls.portfolio_service = get_portfolio_service()
        cls.algo_service = get_algo_trading_service(cls.portfolio_service)
        cls.TradingStrategy = TradingStrategy
    
    def test_technical_indicators(self):
        """Test technical indicator calculations"""
        indicators = self.algo_service.calculate_indicators('SPY')
        
        self.assertIsNotNone(indicators)
        self.assertEqual(indicators.symbol, 'SPY')
        self.assertGreater(indicators.current_price, 0)
        self.assertTrue(0 <= indicators.rsi_14 <= 100)
        self.assertGreater(indicators.sma_20, 0)
        self.assertGreater(indicators.sma_50, 0)
        self.assertGreater(indicators.bb_upper, indicators.bb_lower)
        
        print(f"✓ Technical Indicators for SPY: RSI={indicators.rsi_14:.2f}, MACD={indicators.macd_line:.4f}")
    
    def test_signal_generation_all_strategies(self):
        """Test signal generation for all strategies"""
        strategies = [
            'momentum', 'mean_reversion', 'trend_following',
            'rsi_strategy', 'macd_crossover', 'breakout'
        ]
        
        for strategy_name in strategies:
            strategy = self.TradingStrategy(strategy_name)
            signal = self.algo_service.generate_signal('SPY', strategy)
            
            self.assertIsNotNone(signal)
            self.assertEqual(signal.symbol, 'SPY')
            self.assertEqual(signal.strategy, strategy)
            self.assertTrue(0 <= signal.confidence <= 1)
            self.assertIsNotNone(signal.signal_type)
            self.assertGreater(len(signal.reasoning), 0)
            
            print(f"✓ {strategy_name.upper()}: {signal.signal_type.value} ({signal.confidence*100:.0f}%)")
    
    def test_bot_creation(self):
        """Test trading bot creation"""
        bot = self.algo_service.create_bot(
            account_id='TEST-001',
            name='Test Momentum Bot',
            strategy=self.TradingStrategy.MOMENTUM,
            symbols=['SPY', 'QQQ', 'BTC'],
            max_position_size=500,
            stop_loss_pct=5,
            take_profit_pct=10
        )
        
        self.assertIsNotNone(bot)
        self.assertIn('BOT-', bot.bot_id)
        self.assertEqual(bot.name, 'Test Momentum Bot')
        self.assertEqual(bot.strategy, self.TradingStrategy.MOMENTUM)
        self.assertEqual(len(bot.symbols), 3)
        self.assertTrue(bot.is_active)
        
        print(f"✓ Bot created: {bot.bot_id}")
        
        # Test start/stop
        result = self.algo_service.stop_bot(bot.bot_id)
        self.assertTrue(result['success'])
        self.assertFalse(self.algo_service.bots[bot.bot_id].is_active)
        
        result = self.algo_service.start_bot(bot.bot_id)
        self.assertTrue(result['success'])
        self.assertTrue(self.algo_service.bots[bot.bot_id].is_active)
        
        print(f"✓ Bot start/stop working")
    
    def test_bot_run_cycle(self):
        """Test bot trading cycle execution"""
        # Create a bot
        bot = self.algo_service.create_bot(
            account_id='TEST-002',
            name='Test RSI Bot',
            strategy=self.TradingStrategy.RSI_STRATEGY,
            symbols=['SPY']
        )
        
        # Run a cycle
        results = self.algo_service.run_bot_cycle(bot.bot_id)
        
        self.assertIsInstance(results, list)
        print(f"✓ Bot cycle executed: {len(results)} action(s)")
    
    def test_market_overview(self):
        """Test market overview with signals"""
        overview = self.algo_service.get_market_overview()
        
        self.assertIn('timestamp', overview)
        self.assertIn('assets', overview)
        self.assertGreater(len(overview['assets']), 0)
        
        for asset in overview['assets']:
            self.assertIn('symbol', asset)
            self.assertIn('price', asset)
            self.assertIn('signal', asset)
            self.assertIn('confidence', asset)
        
        print(f"✓ Market Overview: {len(overview['assets'])} assets analyzed")
    
    def test_order_history(self):
        """Test order history retrieval"""
        orders = self.algo_service.get_order_history(limit=10)
        
        self.assertIsInstance(orders, list)
        print(f"✓ Order History: {len(orders)} orders")
    
    def test_signals_retrieval(self):
        """Test signals retrieval"""
        # Generate some signals first
        self.algo_service.generate_signal('SPY', self.TradingStrategy.MOMENTUM)
        self.algo_service.generate_signal('QQQ', self.TradingStrategy.RSI_STRATEGY)
        
        signals = self.algo_service.get_all_signals(limit=20)
        
        self.assertIsInstance(signals, list)
        self.assertGreater(len(signals), 0)
        print(f"✓ Signals: {len(signals)} signals retrieved")
    
    def test_bot_performance(self):
        """Test bot performance metrics"""
        # Create a bot and run some cycles
        bot = self.algo_service.create_bot(
            account_id='TEST-003',
            name='Performance Test Bot',
            strategy=self.TradingStrategy.TREND_FOLLOWING,
            symbols=['SPY', 'BTC']
        )
        
        # Run a few cycles to generate some data
        for _ in range(3):
            self.algo_service.run_bot_cycle(bot.bot_id)
        
        performance = self.algo_service.get_bot_performance(bot.bot_id)
        
        self.assertIn('bot_id', performance)
        self.assertIn('performance', performance)
        self.assertIn('settings', performance)
        self.assertIn('activity', performance)
        
        print(f"✓ Bot Performance: {performance['performance']['total_trades']} trades, {performance['performance']['win_rate']:.1f}% win rate")


class TestAlgoTradingAPI(unittest.TestCase):
    """Test algo trading API endpoints"""
    
    @classmethod
    def setUpClass(cls):
        """Start test server"""
        from web_portal.server import PortalHandler
        from http.server import ThreadingHTTPServer
        
        cls.server = ThreadingHTTPServer(('127.0.0.1', 8765), PortalHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever)
        cls.server_thread.daemon = True
        cls.server_thread.start()
        cls.base_url = 'http://127.0.0.1:8765'
        time.sleep(2)  # Wait for server to start
        print("\n✓ Test server started on port 8765")
    
    @classmethod
    def tearDownClass(cls):
        """Stop test server"""
        cls.server.shutdown()
    
    def _request(self, method, path, data=None):
        """Helper to make HTTP requests"""
        url = f"{self.base_url}{path}"
        
        if data:
            data = json.dumps(data).encode('utf-8')
            req = urllib.request.Request(url, data=data, method=method)
            req.add_header('Content-Type', 'application/json')
        else:
            req = urllib.request.Request(url, method=method)
        
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                body = json.loads(response.read().decode('utf-8'))
                return {'status': response.status, 'body': body}
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode('utf-8'))
            return {'status': e.code, 'body': body}
        except Exception as e:
            return {'status': 500, 'body': {'error': str(e)}}
    
    def test_get_market_overview(self):
        """Test GET /api/algo/market-overview"""
        result = self._request('GET', '/api/algo/market-overview')
        
        self.assertEqual(result['status'], 200)
        self.assertIn('assets', result['body'])
        print(f"✓ GET /api/algo/market-overview: {len(result['body']['assets'])} assets")
    
    def test_get_indicators(self):
        """Test GET /api/algo/indicators"""
        result = self._request('GET', '/api/algo/indicators?symbol=SPY')
        
        self.assertEqual(result['status'], 200)
        self.assertIn('rsi_14', result['body'])
        self.assertIn('macd_line', result['body'])
        print(f"✓ GET /api/algo/indicators: RSI={result['body']['rsi_14']:.2f}")
    
    def test_get_signals(self):
        """Test GET /api/algo/signals"""
        result = self._request('GET', '/api/algo/signals?limit=10')
        
        self.assertEqual(result['status'], 200)
        self.assertIn('signals', result['body'])
        print(f"✓ GET /api/algo/signals: {len(result['body']['signals'])} signals")
    
    def test_create_bot(self):
        """Test POST /api/algo/bots/create"""
        result = self._request('POST', '/api/algo/bots/create', {
            'account_id': 'API-TEST-001',
            'name': 'API Test Bot',
            'strategy': 'momentum',
            'symbols': ['SPY', 'BTC'],
            'max_position_size': 500
        })
        
        self.assertEqual(result['status'], 201)
        self.assertTrue(result['body']['success'])
        self.assertIn('bot', result['body'])
        
        bot_id = result['body']['bot']['bot_id']
        print(f"✓ POST /api/algo/bots/create: {bot_id}")
        
        return bot_id
    
    def test_get_bots(self):
        """Test GET /api/algo/bots"""
        # Create a bot first
        self.test_create_bot()
        
        result = self._request('GET', '/api/algo/bots?account_id=API-TEST-001')
        
        self.assertEqual(result['status'], 200)
        self.assertIn('bots', result['body'])
        print(f"✓ GET /api/algo/bots: {len(result['body']['bots'])} bots")
    
    def test_bot_lifecycle(self):
        """Test bot start, stop, run cycle"""
        # Create bot
        create_result = self._request('POST', '/api/algo/bots/create', {
            'account_id': 'LIFECYCLE-TEST',
            'name': 'Lifecycle Test Bot',
            'strategy': 'rsi_strategy',
            'symbols': ['SPY']
        })
        
        bot_id = create_result['body']['bot']['bot_id']
        
        # Stop bot
        stop_result = self._request('POST', '/api/algo/bots/stop', {'bot_id': bot_id})
        self.assertTrue(stop_result['body']['success'])
        print(f"✓ Bot stopped: {bot_id}")
        
        # Start bot
        start_result = self._request('POST', '/api/algo/bots/start', {'bot_id': bot_id})
        self.assertTrue(start_result['body']['success'])
        print(f"✓ Bot started: {bot_id}")
        
        # Run cycle
        cycle_result = self._request('POST', '/api/algo/bots/run-cycle', {'bot_id': bot_id})
        self.assertTrue(cycle_result['body']['success'])
        print(f"✓ Bot cycle run: {len(cycle_result['body']['results'])} actions")
    
    def test_quick_trade(self):
        """Test POST /api/algo/trade"""
        result = self._request('POST', '/api/algo/trade', {
            'account_id': 'TRADE-TEST',
            'symbol': 'SPY',
            'side': 'buy',
            'amount': 100
        })
        
        self.assertEqual(result['status'], 200)
        self.assertTrue(result['body']['success'])
        self.assertIn('order', result['body'])
        print(f"✓ POST /api/algo/trade: Order {result['body']['order']['order_id']}")
    
    def test_generate_signal(self):
        """Test GET /api/algo/generate-signal"""
        result = self._request('GET', '/api/algo/generate-signal?symbol=BTC&strategy=momentum')
        
        self.assertEqual(result['status'], 200)
        self.assertIn('signal', result['body'])
        signal = result['body']['signal']
        self.assertEqual(signal['symbol'], 'BTC')
        print(f"✓ GET /api/algo/generate-signal: {signal['signal_type']} ({signal['confidence']*100:.0f}%)")


def run_tests():
    """Run all tests"""
    print("\n" + "="*60)
    print("PHINS ALGO TRADING SYSTEM - TEST SUITE")
    print("="*60 + "\n")
    
    # Run service tests
    print("PART 1: Service Unit Tests")
    print("-"*40)
    service_suite = unittest.TestLoader().loadTestsFromTestCase(TestAlgoTradingService)
    service_result = unittest.TextTestRunner(verbosity=0).run(service_suite)
    
    print("\n" + "-"*40)
    print("PART 2: API Integration Tests")
    print("-"*40)
    api_suite = unittest.TestLoader().loadTestsFromTestCase(TestAlgoTradingAPI)
    api_result = unittest.TextTestRunner(verbosity=0).run(api_suite)
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    service_passed = service_result.testsRun - len(service_result.failures) - len(service_result.errors)
    api_passed = api_result.testsRun - len(api_result.failures) - len(api_result.errors)
    
    print(f"Service Tests: {service_passed}/{service_result.testsRun} passed")
    print(f"API Tests: {api_passed}/{api_result.testsRun} passed")
    
    total_passed = service_passed + api_passed
    total_tests = service_result.testsRun + api_result.testsRun
    
    if total_passed == total_tests:
        print(f"\n✅ ALL {total_tests} TESTS PASSED!")
    else:
        print(f"\n⚠️ {total_tests - total_passed} test(s) failed")
    
    return total_passed == total_tests


if __name__ == '__main__':
    success = run_tests()
    exit(0 if success else 1)
