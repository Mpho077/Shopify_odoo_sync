# -*- coding: utf-8 -*-
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    shopify_customer_id = fields.Char(string="Shopify Customer ID", index=True, copy=False)
    shopify_backend_id = fields.Many2one('shopify.backend', string="Shopify Store", copy=False)
