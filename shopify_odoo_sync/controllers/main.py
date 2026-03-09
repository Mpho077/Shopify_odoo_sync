# -*- coding: utf-8 -*-
import base64
import hashlib
import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class ShopifyWebhookController(http.Controller):

    @http.route('/shopify/webhook/<int:backend_id>/<string:topic>', type='http', methods=['POST'], auth='public', csrf=False)
    def webhook(self, backend_id, topic, **kwargs):
        body = request.httprequest.data
        received_hmac = request.httprequest.headers.get('X-Shopify-Hmac-Sha256', '')

        backend = request.env['shopify.backend'].sudo().browse(backend_id)
        if not backend.exists() or backend.state != 'confirmed':
            return request.make_response('Not Found', status=404)

        if backend.webhook_secret:
            if not self._verify_hmac(body, backend.webhook_secret, received_hmac):
                return request.make_response('Unauthorized', status=401)

        try:
            data = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            return request.make_response('Bad Request', status=400)

        real_topic = topic.replace('-', '/')
        
        try:
            self._dispatch(backend, real_topic, data)
        except Exception:
            _logger.exception('Webhook error for %s', real_topic)

        return request.make_response('OK', status=200)

    def _dispatch(self, backend, topic, data):
        if topic in ('products/create', 'products/update'):
            backend._import_single_product(data)
        elif topic == 'products/delete':
            product = backend._get_binding(str(data.get('id', '')), 'product.template')
            if product:
                product.active = False
        elif topic in ('orders/create', 'orders/updated'):
            backend._import_single_order(data)
        elif topic == 'orders/cancelled':
            order = backend._get_binding(str(data.get('id', '')), 'sale.order')
            if order and order.state not in ('cancel', 'done'):
                order.action_cancel()
        elif topic in ('customers/create', 'customers/update'):
            backend._import_single_customer(data)

    @staticmethod
    def _verify_hmac(body_bytes, secret, received_hmac):
        if not received_hmac:
            return False
        computed = base64.b64encode(
            hmac.new(secret.encode('utf-8'), body_bytes, hashlib.sha256).digest()
        ).decode('utf-8')
        return hmac.compare_digest(computed, received_hmac)
