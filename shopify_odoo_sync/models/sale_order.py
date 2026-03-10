# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            order._shopify_auto_invoice()
        return res

    def _shopify_auto_invoice(self):
        """Auto-create invoice and register payment for Shopify orders."""
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('shopify_odoo_sync.auto_create_invoice') != 'True':
            return
        if self.state != 'sale':
            return
        # Detect Shopify orders via shopify_ept fields or origin
        is_shopify = False
        if hasattr(self, 'shopify_instance_id') and self.shopify_instance_id:
            is_shopify = True
        elif self.origin and 'shopify' in (self.origin or '').lower():
            is_shopify = True
        if not is_shopify:
            return
        try:
            invoice = self._create_invoices()
            invoice.action_post()
            if ICP.get_param('shopify_odoo_sync.auto_register_payment') == 'True':
                journal_id = int(ICP.get_param('shopify_odoo_sync.payment_journal_id', '0'))
                if journal_id:
                    journal = self.env['account.journal'].browse(journal_id).exists()
                    if journal:
                        payment_register = self.env['account.payment.register'].with_context(
                            active_model='account.move',
                            active_ids=invoice.ids,
                        ).create({'journal_id': journal.id})
                        payment_register.action_create_payments()
                    else:
                        _logger.warning('Shopify auto-payment: journal %d not found', journal_id)
                else:
                    _logger.warning('Shopify auto-payment: no payment journal configured')
        except Exception as e:
            _logger.exception('Auto-invoice failed for order %s: %s', self.name, e)
