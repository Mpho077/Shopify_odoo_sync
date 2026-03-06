# -*- coding: utf-8 -*-
from odoo import fields, models


class ShopifySyncLog(models.Model):
    _name = 'shopify.sync.log'
    _description = 'Shopify Sync Log'
    _order = 'create_date desc'

    backend_id = fields.Many2one('shopify.backend', string="Backend", required=True, ondelete='cascade')
    sync_type = fields.Selection([
        ('product', 'Product'),
        ('order', 'Order'),
        ('customer', 'Customer'),
        ('price', 'Price'),
        ('webhook', 'Webhook'),
    ], string="Type")
    shopify_id = fields.Char(string="Shopify ID")
    status = fields.Selection([
        ('success', 'Success'),
        ('error', 'Error'),
        ('skipped', 'Skipped'),
    ], string="Status")
    message = fields.Text(string="Message")
