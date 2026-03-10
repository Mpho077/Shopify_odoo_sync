# -*- coding: utf-8 -*-
from odoo import fields, models


class ShopifySyncLog(models.Model):
    """Stub model kept for database compatibility."""
    _name = 'shopify.sync.log'
    _description = 'Shopify Sync Log (Deprecated)'
    _order = 'create_date desc'

    backend_id = fields.Many2one('shopify.backend', string="Backend", ondelete='cascade')
    sync_type = fields.Char(string="Type")
    shopify_id = fields.Char(string="Shopify ID")
    status = fields.Char(string="Status")
    message = fields.Text(string="Message")
