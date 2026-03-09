# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    shopify_backend_id = fields.Many2one('shopify.backend', string="Shopify Store", copy=False)
    shopify_product_id = fields.Char(string="Shopify Product ID", index=True, copy=False)
    shopify_handle = fields.Char(string="Shopify Handle", copy=False)
    shopify_synced = fields.Boolean(compute='_compute_shopify_synced', store=False)
    description_sale = fields.Text(string="Sale Description")

    def _compute_shopify_synced(self):
        for rec in self:
            rec.shopify_synced = bool(rec.shopify_product_id)

    def action_sync_from_shopify(self):
        self.ensure_one()
        if not self.shopify_product_id or not self.shopify_backend_id:
            raise UserError(_('This product is not linked to Shopify.'))

        backend = self.shopify_backend_id
        result = backend._shopify_request('GET', f'products/{self.shopify_product_id}.json')
        
        if 'error' in result or 'errors' in result:
            raise UserError(str(result.get('error') or result.get('errors')))
        
        product_data = result.get('product')
        if product_data:
            backend._import_single_product(product_data)

    def action_view_in_shopify(self):
        self.ensure_one()
        if not self.shopify_product_id or not self.shopify_backend_id:
            raise UserError(_('This product is not linked to Shopify.'))

        shop_url = self.shopify_backend_id.shop_url.strip().rstrip('/')
        if not shop_url.startswith('http'):
            shop_url = f"https://{shop_url}"
        
        return {
            'type': 'ir.actions.act_url',
            'url': f"{shop_url}/admin/products/{self.shopify_product_id}",
            'target': 'new',
        }
