# -*- coding: utf-8 -*-
{
    'name': 'Shopify Auto Invoice & Price Sync',
    'version': '3.0.0',
    'category': 'Sales',
    'sequence': 10,
    'summary': 'Auto-invoice Shopify orders and sync prices from Shopify to Odoo',
    'description': """
Shopify Auto Invoice & Price Sync
=================================

Companion module for shopify_ept.

**Auto Invoice**
- Automatically create and post invoices when Shopify orders are confirmed
- Auto-register payments with configurable journal
- Settings in Sales > Configuration > Settings

**Price Sync (Shopify to Odoo)**
- Pull product prices from Shopify into Odoo
- Match products by SKU
- Update product sale price and/or pricelist items
- Automatic cron job every 2 hours
- Manual sync button
- Configure in Sales > Configuration > Shopify Price Sync
    """,
    'author': 'Custom',
    'website': '',
    'license': 'LGPL-3',
    'depends': [
        'sale_management',
        'account',
        'product',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/shopify_backend_views.xml',
        'views/shopify_log_views.xml',
        'views/shopify_price_sync_views.xml',
        'views/product_views.xml',
        'views/sale_order_views.xml',
        'views/menus.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
