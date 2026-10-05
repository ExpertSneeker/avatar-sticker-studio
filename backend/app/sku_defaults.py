"""Defaults for newly selected specifications and a one-time existing-SKU update."""
import re

# Kept in sync with frontend/src/lib/agiso.ts; both sides have contract tests.
SPEC_QUOTAS = {
    42: (50, 42, 18),
    36: (42, 36, 15),
    30: (35, 30, 12),
    24: (30, 24, 9),
    18: (24, 18, 7),
    12: (16, 12, 6),
    6: (8, 6, 3),
    1: (3, 1, 1),
}


def spec_quotas(name):
    for quantity in (42, 36, 30, 24, 18, 12, 6, 1):
        if re.search(rf'(?<![\d.]){quantity}[个张]', name):
            return SPEC_QUOTAS.get(quantity)
    return None


def migrate_sku_defaults(tx):
    if tx.get('migrations', 'sku-spec-defaults-v1'):
        return
    for shop in tx.all('agiso_shops'):
        changed = False
        for rule in shop.get('rules', []):
            before = dict(rule)
            rule['enabled'] = True
            quotas = spec_quotas(rule.get('sku_name', ''))
            if quotas:
                rule.update(zip(('generation_limit', 'final_count', 'rerun_limit'), quotas))
            changed |= rule != before
        if changed:
            tx.put('agiso_shops', shop)
    tx.put('migrations', {'id': 'sku-spec-defaults-v1'})
