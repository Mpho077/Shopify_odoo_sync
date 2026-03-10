# -*- coding: utf-8 -*-
from odoo import fields, models


class ShopifyBackend(models.Model):
    """Stub model kept for database compatibility.
    All sync functionality is now handled by shopify_ept.
    Auto-invoice settings are in Sales > Configuration > Settings.
    """
    _name = 'shopify.backend'
    _description = 'Shopify Backend (Deprecated - use Shopify EPT)'
    _order = 'name'

    name = fields.Char(string="Name", required=True, default="Deprecated")
    active = fields.Boolean(default=False)
