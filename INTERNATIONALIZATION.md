# PHINS Global Platform - Internationalization & Scalability Guide

## Overview

PHINS is now a globally-ready, scalable insurance management platform supporting **20 major languages** with optimization for **millions of concurrent users**. This guide explains the internationalization (i18n), localization (l10n), and performance features.

---

## Table of Contents

1. [Supported Languages](#supported-languages)
2. [Using Translations](#using-translations)
3. [Locale Formatting](#locale-formatting)
4. [Configuration](#configuration)
5. [Performance Optimization](#performance-optimization)
6. [Scalability Features](#scalability-features)
7. [Multi-Language UI](#multi-language-ui)
8. [Deployment](#deployment)

---

## Supported Languages

PHINS supports 20 of the world's most spoken languages:

| Code | Language | Native Name | Region |
|------|----------|-------------|--------|
| en | English | English | Global |
| zh | Mandarin Chinese | 中文 | China, Taiwan |
| hi | Hindi | हिन्दी | India |
| es | Spanish | Español | Spain, Latin America |
| fr | French | Français | France, Africa |
| ar | Arabic | العربية | Middle East, North Africa |
| pt | Portuguese | Português | Portugal, Brazil |
| ru | Russian | Русский | Russia, Eastern Europe |
| ja | Japanese | 日本語 | Japan |
| de | German | Deutsch | Germany, Austria |
| it | Italian | Italiano | Italy |
| ko | Korean | 한국어 | South Korea |
| tr | Turkish | Türkçe | Turkey |
| vi | Vietnamese | Tiếng Việt | Vietnam |
| nl | Dutch | Nederlands | Netherlands, Belgium |
| pl | Polish | Polski | Poland |
| sv | Swedish | Svenska | Sweden |
| el | Greek | Ελληνικά | Greece |
| he | Hebrew | עברית | Israel |
| id | Indonesian | Bahasa Indonesia | Indonesia |

---

## Using Translations

### Basic Translation

```python
from i18n import get_translator, Language, translate, t

# Method 1: Using global function
message = translate("app_name")  # Returns in current language

# Method 2: Using shorthand
message = t("division_sales")

# Method 3: Using translator instance
translator = get_translator()
message = translator.t("status_active")

# Method 4: Specify language
translator.set_language(Language.ES)
message = translator.t("division_claims")  # Returns Spanish
```

### Adding New Translations

```python
from i18n import TranslationManager, Language

# Add to TRANSLATIONS dictionary in i18n.py
TranslationManager.TRANSLATIONS["my_new_key"] = {
    "en": "English Text",
    "es": "Texto en Español",
    "zh": "中文文本",
    "hi": "हिंदी पाठ",
    # ... add all 20 languages
}
```

### Supported Translation Keys

**Divisions:**
- `division_sales`, `division_underwriting`, `division_claims`, `division_accounting`
- `division_actuarial`, `division_reinsurance`

**Status Fields:**
- `status_active`, `status_pending`, `status_approved`, `status_rejected`

**Actions:**
- `action_create`, `action_edit`, `action_delete`, `action_save`
- `action_view`, `action_cancel`

**Common Fields:**
- `field_id`, `field_name`, `field_email`, `field_phone`
- `field_address`, `field_amount`, `field_date`, `field_status`

**Messages:**
- `msg_success`, `msg_error`, `msg_confirm`

---

## Locale Formatting

### Currency Formatting

```python
from i18n import LocaleFormatter, Language
from decimal import Decimal

amount = Decimal("1234.56")

# Format in different locales
us_format = LocaleFormatter.format_currency(amount, Language.EN)   # $ 1,234.56
de_format = LocaleFormatter.format_currency(amount, Language.DE)   # $ 1.234,56
fr_format = LocaleFormatter.format_currency(amount, Language.FR)   # $ 1 234,56
pt_format = LocaleFormatter.format_currency(amount, Language.PT)   # R$ 1.234,56
ja_format = LocaleFormatter.format_currency(amount, Language.JA)   # ¥ 1,234.56
```

### Date Formatting

```python
from datetime import datetime

now = datetime.now()

# Format in different locales
us_date = LocaleFormatter.format_date(now, Language.EN)   # 12/09/2025
de_date = LocaleFormatter.format_date(now, Language.DE)   # 09.12.2025
fr_date = LocaleFormatter.format_date(now, Language.FR)   # 09/12/2025
zh_date = LocaleFormatter.format_date(now, Language.ZH)   # 2025年12月09日
```

### Number Formatting

```python
# Format numbers with locale-specific decimal separator
number = 1234.567

en_format = LocaleFormatter.format_number(number, 2, Language.EN)   # 1,234.57
de_format = LocaleFormatter.format_number(number, 2, Language.DE)   # 1.234,57
```

---

## Configuration

### Global Configuration (`config.py`)

```python
from config import PHINSConfig, Environment

# Check current environment
print(PHINSConfig.ENVIRONMENT)  # Environment.PRODUCTION

# Access configuration
print(PHINSConfig.PAGE_SIZE)           # 50
print(PHINSConfig.MAX_PAGE_SIZE)       # 1000
print(PHINSConfig.CACHE_TTL_SECONDS)   # 3600
print(PHINSConfig.DEFAULT_LANGUAGE)    # Language.EN

# Check if feature is enabled
if PHINSConfig.is_feature_enabled("multi_language"):
    print("Multi-language support enabled")

# Get enabled features
features = PHINSConfig.get_enabled_features()
# ['file_management', 'multi_language', 'actuarial', ...]
```

### Performance Configuration

```python
from config import PerformanceOptimizations

# Get optimization profile for expected user load
profile = PerformanceOptimizations.get_optimization_profile(1000000)
# Returns tuned settings for 1 million users
```

### Feature Flags

```python
# Check specific features
PHINSConfig.FEATURES["actuarial"]          # True
PHINSConfig.FEATURES["reinsurance"]        # True
PHINSConfig.FEATURES["customer_portal"]    # True
```

---

## Performance Optimization

### Caching

```python
from scalability import get_cache, CacheStrategy

cache = get_cache()

# Store data with 1-hour TTL
cache.set("company:123", company_object, ttl_seconds=3600)

# Retrieve data
company = cache.get("company:123")

# Check cache statistics
stats = cache.get_stats()
print(f"Cache hit rate: {stats['hit_rate']}%")
print(f"Cache size: {stats['size']}/{stats['max_size']}")
```

### Pagination

```python
from scalability import get_query_optimizer

optimizer = get_query_optimizer()

# Paginate results (50 items per page)
result = optimizer.paginate(items, page=2, page_size=50)
# Returns: {'items': [...], 'page': 2, 'total': 1000, 'total_pages': 20, ...}
```

### Batch Processing

```python
# Process large datasets in memory-efficient batches
def process_batch(batch):
    return [item.upper() for item in batch]

items = ["a", "b", "c", ... ]  # Large list
results = optimizer.batch_process(items, batch_size=100, processor=process_batch)
```

### Query Performance Tracking

```python
import time

start = time.time()
# ... execute query ...
duration_ms = (time.time() - start) * 1000

optimizer.record_query("get_policies", duration_ms)

# Get performance statistics
stats = optimizer.get_query_stats()
slow = optimizer.get_slow_queries()
```

---

## Scalability Features

### Connection Pooling

```python
from scalability import get_connection_pool

pool = get_connection_pool()

# Acquire connection
if pool.acquire():
    try:
        # ... use connection ...
    finally:
        pool.release()

# Check pool status
stats = pool.get_stats()
# {'total': 20, 'available': 15, 'in_use': 5}
```

### Rate Limiting

```python
from scalability import get_rate_limiter

limiter = get_rate_limiter()

user_id = "user@example.com"

# Check if user can proceed
if limiter.is_allowed(user_id):
    # Process request
    pass
else:
    # Return 429 Too Many Requests
    pass

# Check remaining requests
remaining = limiter.get_remaining(user_id)
```

### Performance Monitoring

```python
from scalability import get_performance_monitor

monitor = get_performance_monitor()

# Record metrics
monitor.record_metric("policy_create_time_ms", 150.5)

# Get metric summary
summary = monitor.get_metric_summary("policy_create_time_ms")
# {'count': 100, 'average': 145.2, 'min': 120, 'max': 250, 'total': 14520}

# Check system health
health = monitor.get_health_status()
# {'status': 'healthy', 'uptime': {...}, 'timestamp': '...'}
```

---

## Multi-Language UI

### Setting User Language

```python
from i18n import set_global_language, Language

# Set platform language to Spanish
set_global_language(Language.ES)

# All subsequent translations use Spanish
print(t("division_sales"))  # "Ventas"
print(t("status_active"))   # "Activo"
```

### Language Selection Menu

```python
from i18n import get_translator

translator = get_translator()

# Get all available languages
languages = translator.get_all_languages()
# [
#   (Language.EN, "English"),
#   (Language.ZH, "中文 (Chinese)"),
#   (Language.ES, "Español (Spanish)"),
#   ...
# ]

# Render in UI
for lang, name in languages:
    print(f"{lang.value}: {name}")
```

### Regional Formatting

```python
from i18n import LocaleFormatter, Language
from decimal import Decimal
from datetime import datetime

# Single function handles all locale-specific formatting
user_language = Language.DE
premium = Decimal("5000.00")
policy_date = datetime(2025, 12, 9)

formatted_premium = LocaleFormatter.format_currency(premium, user_language)
formatted_date = LocaleFormatter.format_date(policy_date, user_language)

# German user sees: 5.000,00€ on 09.12.2025
```

---

## Deployment

### Production Configuration

```python
# In deployment, set environment and config
from config import PHINSConfig, Environment

PHINSConfig.ENVIRONMENT = Environment.PRODUCTION
PHINSConfig.DEBUG = False
PHINSConfig.ENABLE_CACHE = True
PHINSConfig.CACHE_TTL_SECONDS = 1800

# Set for expected load
from config import PerformanceOptimizations
profile = PerformanceOptimizations.get_optimization_profile(5000000)
# Configure database, cache, workers based on profile
```

### Health Check Endpoint

```python
from scalability import get_performance_monitor, get_cache

def health_check():
    monitor = get_performance_monitor()
    cache = get_cache()
    
    return {
        "status": "healthy",
        "system": monitor.get_health_status(),
        "cache": cache.get_stats(),
        "config": PHINSConfig.get_config_summary(),
    }
```

### Metrics Export

```python
from scalability import get_query_optimizer, get_performance_monitor

def export_metrics():
    optimizer = get_query_optimizer()
    monitor = get_performance_monitor()
    
    return {
        "query_performance": optimizer.get_query_stats(),
        "slow_queries": optimizer.get_slow_queries(),
        "system_metrics": {
            "uptime": monitor.get_uptime(),
            "health": monitor.get_health_status(),
        },
    }
```

---

## Data Validation

```python
from config import DataValidation

# Validate email
if DataValidation.validate_email("user@example.com"):
    print("Valid email")

# Validate phone
if DataValidation.validate_phone("+14155552671"):
    print("Valid phone")

# Check field lengths
if DataValidation.validate_field_length("email", "user@example.com"):
    print("Email within length limits")
```

---

## Best Practices

### 1. Always Use Translation Keys
```python
# ✓ Good
label = t("field_email")

# ✗ Bad
label = "Email"  # Not translatable
```

### 2. Cache Static Data
```python
# ✓ Good - cache health tables
health_table = cache.get("health_table:HLT123")
if not health_table:
    health_table = load_from_db()
    cache.set("health_table:HLT123", health_table, ttl_seconds=86400)

# ✗ Bad - query every time
health_table = load_from_db()
```

### 3. Use Pagination for Large Results
```python
# ✓ Good
policies = get_policies()  # All 10,000
paginated = optimizer.paginate(policies, page=1, page_size=50)

# ✗ Bad
policies = get_policies()[:50]  # Still loaded all 10,000 first
```

### 4. Monitor Slow Queries
```python
# ✓ Good
monitor.record_query("get_claims", execution_time_ms)
slow_queries = optimizer.get_slow_queries()  # Track and optimize

# ✗ Bad
# Assume everything is fast, no tracking
```

### 5. Respect Rate Limits
```python
# ✓ Good
if limiter.is_allowed(user_id):
    process_request()
else:
    return "Too many requests"

# ✗ Bad
process_request()  # No rate limiting
```

---

## Troubleshooting

### Translations Missing
```python
from i18n import TranslationManager

# Check if key exists
if "my_key" in TranslationManager.TRANSLATIONS:
    print("Key found")
else:
    print("Key missing - add to TRANSLATIONS dictionary")
```

### Cache Not Working
```python
cache = get_cache()
stats = cache.get_stats()

if stats['hit_rate'] < 50:
    print("Cache hit rate low - consider increasing TTL or cache size")
```

### Performance Issues
```python
from scalability import get_query_optimizer

slow = optimizer.get_slow_queries()
for query, stats in slow:
    print(f"{query}: avg {stats['avg_ms']:.2f}ms (slow: {stats['slow_count']})")
```

---

## Quick Start Example

```python
#!/usr/bin/env python3
"""
PHINS Global Platform Demo
Shows multi-language, high-performance capabilities
"""

from i18n import get_translator, Language, LocaleFormatter
from config import PHINSConfig
from scalability import get_cache, get_query_optimizer
from decimal import Decimal
from datetime import datetime

def main():
    # 1. Set language to Spanish
    translator = get_translator()
    translator.set_language(Language.ES)
    print(f"Platform: {translator.t('app_name')}")
    
    # 2. Format currency and date in local format
    premium = Decimal("50000.00")
    date = datetime.now()
    print(f"Premium: {LocaleFormatter.format_currency(premium, Language.ES)}")
    print(f"Date: {LocaleFormatter.format_date(date, Language.ES)}")
    
    # 3. Cache operations data
    cache = get_cache()
    cache.set("premium_es", premium, ttl_seconds=3600)
    
    # 4. Paginate large results
    optimizer = get_query_optimizer()
    large_list = list(range(1000))
    page1 = optimizer.paginate(large_list, page=1, page_size=50)
    print(f"Page {page1['page']} of {page1['total_pages']}")
    
    # 5. Check configuration
    print(f"\nConfiguration:")
    print(f"  Environment: {PHINSConfig.ENVIRONMENT.value}")
    print(f"  Cache enabled: {PHINSConfig.ENABLE_CACHE}")
    print(f"  Page size: {PHINSConfig.PAGE_SIZE}")
    
    # 6. Check cache stats
    stats = cache.get_stats()
    print(f"\nCache Stats:")
    print(f"  Hit rate: {stats['hit_rate']}%")
    print(f"  Size: {stats['size']}/{stats['max_size']}")

if __name__ == "__main__":
    main()
```

---

## Support

For issues or questions:
1. Check the `INTERNATIONALIZATION.md` file
2. Review examples in `demo_multi_language.py` (coming soon)
3. Consult `config.py` for available options
4. Check `scalability.py` for performance features

---

## License

PHINS Global Platform © 2025 - MIT License
