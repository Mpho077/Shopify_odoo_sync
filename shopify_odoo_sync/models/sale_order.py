# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    shopify_backend_id = fields.Many2one('shopify.backend', string="Shopify Store", copy=False)
    shopify_order_id = fields.Char(string="Shopify Order ID", index=True, copy=False)
    shopify_order_number = fields.Char(string="Shopify Order #", copy=False)
    shopify_financial_status = fields.Char(string="Payment Status", copy=False)
    shopify_fulfillment_status = fields.Char(string="Fulfillment Status", copy=False)

    def action_sync_from_shopify(self):
        self.ensure_one()
        if not self.shopify_order_id or not self.shopify_backend_id:
            raise UserError(_('This order is not linked to Shopify.'))

        backend = self.shopify_backend_id
        result = backend._shopify_request('GET', f'orders/{self.shopify_order_id}.json')
        
        if 'error' in result or 'errors' in result:
            raise UserError(str(result.get('error') or result.get('errors')))
        
        order_data = result.get('order')
        if order_data:
            backend._import_single_order(order_data)

    def action_view_in_shopify(self):
        self.ensure_one()
        if not self.shopify_order_id or not self.shopify_backend_id:
            raise UserError(_('This order is not linked to Shopify.'))

        shop_url = self.shopify_backend_id.shop_url.strip().rstrip('/')
        if not shop_url.startswith('http'):
            shop_url = f"https://{shop_url}"
        
        return {
            'type': 'ir.actions.act_url',
            'url': f"{shop_url}/admin/orders/{self.shopify_order_id}",
            'target': 'new',
        }


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    shopify_line_item_id = fields.Char(string="Shopify Line ID", index=True, copy=False)
