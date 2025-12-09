#!/usr/bin/env python3
"""
PHINS Global Multi-Language & Performance Demo
Demonstrates:
- 20-language support with automatic locale formatting
- High-performance caching and pagination
- Configuration for millions of users
- Real-world workflows in multiple languages
"""

from datetime import datetime
from decimal import Decimal
from i18n import (
    get_translator, Language, LocaleFormatter, TranslationManager
)
from config import PHINSConfig, PerformanceOptimizations, DataValidation
from scalability import (
    get_cache, get_query_optimizer, get_performance_monitor,
    get_rate_limiter, get_connection_pool
)


def demo_language_selection():
    """Demo 1: Support for all 20 languages"""
    print("\n" + "="*70)
    print("DEMO 1: 20-Language Support")
    print("="*70)
    
    translator = get_translator()
    
    print("\nAvailable Languages:")
    for lang, name in translator.get_all_languages():
        print(f"  {lang.value:3s} → {name}")


def demo_translations(language: Language):
    """Demo 2: Translations in different languages"""
    print("\n" + "="*70)
    print(f"DEMO 2: Translations in {TranslationManager.TRANSLATIONS.get('app_name', {}).get(language.value, language.value)}")
    print("="*70)
    
    translator = get_translator()
    translator.set_language(language)
    
    divisions = [
        "division_sales",
        "division_underwriting",
        "division_claims",
        "division_accounting",
        "division_actuarial",
        "division_reinsurance",
    ]
    
    print("\nDivisions:")
    for div_key in divisions:
        print(f"  {translator.t(div_key)}")
    
    print("\nCommon Actions:")
    actions = ["action_create", "action_edit", "action_save", "action_delete"]
    for action_key in actions:
        print(f"  {translator.t(action_key)}")


def demo_locale_formatting():
    """Demo 3: Locale-aware formatting of currency and dates"""
    print("\n" + "="*70)
    print("DEMO 3: Locale-Specific Currency & Date Formatting")
    print("="*70)
    
    premium = Decimal("125000.50")
    date = datetime(2025, 12, 9)
    
    test_locales = [
        Language.EN,  # USA: $125,000.50
        Language.DE,  # Germany: $125.000,50
        Language.FR,  # France: $125 000,50
        Language.ES,  # Spain: $125.000,50
        Language.ZH,  # China: ¥125,000.50
        Language.JA,  # Japan: ¥125,000.50
        Language.PT,  # Brazil: R$125.000,50
        Language.RU,  # Russia: ₽125 000,50
        Language.IT,  # Italy: €125.000,50
        Language.KO,  # Korea: ₩125,000.50
    ]
    
    print("\nPremium Formatting:")
    for locale in test_locales:
        formatted = LocaleFormatter.format_currency(premium, locale)
        date_fmt = LocaleFormatter.format_date(date, locale)
        print(f"  {locale.value:3s}: {formatted:20s} | {date_fmt}")


def demo_caching_performance():
    """Demo 4: High-performance caching for millions of users"""
    print("\n" + "="*70)
    print("DEMO 4: Caching & Performance")
    print("="*70)
    
    cache = get_cache()
    
    # Simulate policy lookups
    print("\nCache Simulation (1000 policy lookups):")
    for i in range(1000):
        policy_id = f"POL{i % 10}"  # Only 10 unique policies
        
        # First lookup - cache miss
        cached = cache.get(policy_id)
        if not cached:
            # Simulate expensive database query
            policy_data = {"id": policy_id, "premium": Decimal("5000.00")}
            cache.set(policy_id, policy_data, ttl_seconds=3600)
        else:
            # Cache hit - instant retrieval
            pass
    
    stats = cache.get_stats()
    print(f"\n  Total lookups: {stats['hits'] + stats['misses']}")
    print(f"  Cache hits: {stats['hits']}")
    print(f"  Cache misses: {stats['misses']}")
    print(f"  Hit rate: {stats['hit_rate']}%")
    print(f"  Cache size: {stats['size']}/{stats['max_size']}")
    print(f"  Evictions: {stats['evictions']}")


def demo_pagination():
    """Demo 5: Efficient pagination for large result sets"""
    print("\n" + "="*70)
    print("DEMO 5: Pagination for Millions of Records")
    print("="*70)
    
    optimizer = get_query_optimizer()
    
    # Simulate 10,000 policies
    policies = [f"POLICY_{i}" for i in range(10000)]
    
    print("\nPagination Results:")
    page_result = optimizer.paginate(policies, page=1, page_size=100)
    
    print(f"  Total policies: {page_result['total']}")
    print(f"  Page size: {page_result['page_size']}")
    print(f"  Total pages: {page_result['total_pages']}")
    print(f"  Current page: {page_result['page']}")
    print(f"  Items on page: {len(page_result['items'])}")
    print(f"  First item: {page_result['items'][0]}")
    print(f"  Last item: {page_result['items'][-1]}")
    
    # Navigate to page 50
    page_result = optimizer.paginate(policies, page=50, page_size=100)
    print(f"\n  Page 50: {len(page_result['items'])} items")
    print(f"  Has next: {page_result['has_next']}")
    print(f"  Has previous: {page_result['has_previous']}")


def demo_rate_limiting():
    """Demo 6: Rate limiting for API protection"""
    print("\n" + "="*70)
    print("DEMO 6: Rate Limiting")
    print("="*70)
    
    limiter = get_rate_limiter()
    
    print("\nRate Limit Check:")
    user_id = "john@example.com"
    
    # Simulate requests
    allowed = 0
    for i in range(1010):  # Try 1010 requests (limit is 1000/hour)
        if limiter.is_allowed(user_id):
            allowed += 1
        else:
            print(f"  Request #{i+1}: DENIED (rate limit exceeded)")
            break
    
    print(f"  Allowed requests: {allowed}")
    remaining = limiter.get_remaining(user_id)
    print(f"  Remaining requests: {remaining}")


def demo_performance_monitoring():
    """Demo 7: Performance monitoring and metrics"""
    print("\n" + "="*70)
    print("DEMO 7: Performance Monitoring")
    print("="*70)
    
    monitor = get_performance_monitor()
    optimizer = get_query_optimizer()
    
    # Simulate query execution
    import time
    
    print("\nQuery Performance Recording:")
    for i in range(5):
        start = time.time()
        time.sleep(0.01 + i * 0.002)  # Simulate varying query times
        duration_ms = (time.time() - start) * 1000
        optimizer.record_query("create_policy", duration_ms)
        monitor.record_metric("policy_creation_ms", duration_ms)
    
    # Get performance stats
    query_stats = optimizer.get_query_stats()
    if "create_policy" in query_stats:
        stats = query_stats["create_policy"]
        print(f"\n  Query: create_policy")
        print(f"    Count: {stats['count']}")
        print(f"    Avg: {stats['avg_ms']:.2f}ms")
        print(f"    Min: {stats['min_ms']:.2f}ms")
        print(f"    Max: {stats['max_ms']:.2f}ms")
    
    # System uptime
    uptime = monitor.get_uptime()
    print(f"\n  System uptime: {uptime['uptime_readable']}")
    
    health = monitor.get_health_status()
    print(f"  Health status: {health['status']}")


def demo_connection_pooling():
    """Demo 8: Connection pooling for database efficiency"""
    print("\n" + "="*70)
    print("DEMO 8: Connection Pooling")
    print("="*70)
    
    pool = get_connection_pool()
    
    print("\nConnection Pool Status:")
    stats = pool.get_stats()
    print(f"  Total connections: {stats['total']}")
    print(f"  Available: {stats['available']}")
    print(f"  In use: {stats['in_use']}")
    
    # Simulate acquiring connections
    print("\nSimulating 5 concurrent requests:")
    for i in range(5):
        if pool.acquire():
            stats = pool.get_stats()
            print(f"  Request {i+1}: Connection acquired (In use: {stats['in_use']})")
        else:
            print(f"  Request {i+1}: No connections available (waiting...)")
    
    # Release connections
    print("\nReleasing connections:")
    for i in range(5):
        pool.release()
        stats = pool.get_stats()
        print(f"  Released: In use now {stats['in_use']}")


def demo_data_validation():
    """Demo 9: Data validation"""
    print("\n" + "="*70)
    print("DEMO 9: Data Validation")
    print("="*70)
    
    print("\nEmail Validation:")
    emails = [
        "john@example.com",
        "invalid.email",
        "alice+tag@company.org",
        "no-domain@",
    ]
    
    for email in emails:
        valid = DataValidation.validate_email(email)
        status = "✓ Valid" if valid else "✗ Invalid"
        print(f"  {email:25s} → {status}")
    
    print("\nPhone Validation:")
    phones = [
        "+14155552671",
        "555-1234",
        "+86 10 5555 5555",
        "invalid",
    ]
    
    for phone in phones:
        valid = DataValidation.validate_phone(phone)
        status = "✓ Valid" if valid else "✗ Invalid"
        print(f"  {phone:20s} → {status}")


def demo_configuration():
    """Demo 10: Global configuration for millions of users"""
    print("\n" + "="*70)
    print("DEMO 10: Configuration & Scalability")
    print("="*70)
    
    print("\nPHINS Configuration:")
    config = PHINSConfig.get_config_summary()
    for key, value in config.items():
        print(f"  {key:30s}: {value}")
    
    print("\nEnabled Features:")
    features = PHINSConfig.get_enabled_features()
    for feature in features:
        print(f"  ✓ {feature}")
    
    print("\nPerformance Profile for 1 Million Users:")
    profile = PerformanceOptimizations.get_optimization_profile(1000000)
    for key, value in profile.items():
        print(f"  {key:30s}: {value}")


def demo_real_world_workflow():
    """Demo 11: Real-world multi-language workflow"""
    print("\n" + "="*70)
    print("DEMO 11: Real-World Workflow - Policy Creation in 3 Languages")
    print("="*70)
    
    languages = [Language.EN, Language.ES, Language.ZH]
    translator = get_translator()
    cache = get_cache()
    
    for lang in languages:
        translator.set_language(lang)
        
        print(f"\n{TranslationManager.TRANSLATIONS['app_name'][lang.value]}:")
        print("-" * 50)
        
        # Policy creation workflow
        print(f"  {translator.t('action_create')} {translator.t('field_name')}: John Smith")
        print(f"  {translator.t('field_email')}: john@example.com")
        print(f"  {translator.t('field_phone')}: +1 415 555 2671")
        
        # Premium calculation
        premium = Decimal("5000.00")
        formatted_premium = LocaleFormatter.format_currency(premium, lang)
        print(f"  {translator.t('field_amount')}: {formatted_premium}")
        
        # Cache policy
        policy_id = f"POL_demo_{lang.value}"
        cache.set(policy_id, {
            "id": policy_id,
            "status": translator.t("status_pending"),
            "premium": premium,
        }, ttl_seconds=3600)
        
        print(f"  {translator.t('msg_success')}")


def main():
    """Run all demonstrations"""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 68 + "║")
    print("║" + "PHINS Global Insurance Platform - Multi-Language & Performance Demo".center(68) + "║")
    print("║" + " " * 68 + "║")
    print("╚" + "=" * 68 + "╝")
    
    try:
        # Run all demonstrations
        demo_language_selection()
        
        # Show translations in multiple languages
        demo_translations(Language.EN)
        demo_translations(Language.ES)
        demo_translations(Language.ZH)
        
        # Performance demos
        demo_locale_formatting()
        demo_caching_performance()
        demo_pagination()
        demo_rate_limiting()
        demo_performance_monitoring()
        demo_connection_pooling()
        
        # Validation demo
        demo_data_validation()
        
        # Configuration
        demo_configuration()
        
        # Real-world workflow
        demo_real_world_workflow()
        
        # Summary
        print("\n" + "="*70)
        print("DEMO SUMMARY")
        print("="*70)
        print("""
PHINS Global Platform Ready for:
  ✓ 20 Languages (English, Spanish, Chinese, French, German, etc.)
  ✓ Millions of concurrent users (with caching & rate limiting)
  ✓ High performance (pagination, connection pooling, monitoring)
  ✓ Global currency & date formatting (locale-aware)
  ✓ Enterprise features (audit logs, encryption, data validation)
  ✓ Simple maintenance (no external dependencies)

Key Components:
  - i18n.py            : 20-language translation system
  - config.py          : Global configuration & feature flags
  - scalability.py     : Performance optimization & monitoring
  - phins_system.py    : Core insurance business logic
  
Ready for production deployment! 🚀
        """)
        
    except Exception as e:
        print(f"\n❌ Error during demo: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
