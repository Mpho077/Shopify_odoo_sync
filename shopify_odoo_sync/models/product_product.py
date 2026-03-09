# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    shopify_variant_id = fields.Char(string="Shopify Variant ID", index=True, copy=False)
    shopify_inventory_item_id = fields.Char(string="Shopify Inventory Item ID", copy=False)
