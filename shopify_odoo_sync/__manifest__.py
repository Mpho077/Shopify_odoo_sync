# -*- coding: utf-8 -*-
{
    'name': 'Shopify Odoo Sync',
    'version': '1.0.0',
    'category': 'Sales',
    'sequence': 10,
    'summary': 'Sync products, orders, prices between Shopify and Odoo',
    'description': """
Shopify Odoo Synchronization
============================

Complete standalone Shopify integration for Odoo 19.

**Product Sync (Shopify → Odoo)**
- Import products with all fields (title, description, SKU, price, weight, barcode)
- Automatic updates when products change in Shopify
- Image synchronization
- Variant support

**Order Sync (Shopify → Odoo)**
- Import orders from Shopify
- Auto-create customers
- Order line updates (add/remove products)
- Payment and fulfillment status tracking

**Price Sync**
- Import prices from Shopify to Odoo
- Update product list prices
- Pricelist integration

**Features**
- Multiple Shopify store support
- Webhook support for real-time sync
- Scheduled cron jobs
- Detailed sync logging
- Manual sync actions
    """,
    'author': 'Custom',
    'website': '',
    'license': 'LGPL-3',
    'depends': [
        'sale_management',
        'stock',
        'product',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/shopify_backend_views.xml',
        'views/shopify_log_views.xml',
        'views/product_views.xml',
        'views/sale_order_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
