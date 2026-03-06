# -*- coding: utf-8 -*-
import base64
import json
import logging
import re
import time
from datetime import datetime

import requests

from odoo import api, fields, models, _, Command
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

SHOPIFY_API_VERSION = '2024-01'
REQUEST_TIMEOUT = 30


class ShopifyBackend(models.Model):
    _name = 'shopify.backend'
    _description = 'Shopify Store Connection'
    _order = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # =====================
    # Connection fields
    # =====================
    name = fields.Char(string="Store Name", required=True, tracking=True)
    active = fields.Boolean(default=True)
    shop_url = fields.Char(
        string="Shop URL",
        required=True,
        help="Your Shopify store URL, e.g. mystore.myshopify.com",
        tracking=True,
    )
    api_key = fields.Char(
        string="Admin API Access Token",
        help="From Shopify Admin > Settings > Apps > Develop apps",
        copy=False,
        groups='base.group_system',
    )
    webhook_secret = fields.Char(
        string="Webhook Secret",
        copy=False,
        groups='base.group_system',
    )
    api_version = fields.Char(
        string="API Version",
        default=SHOPIFY_API_VERSION,
        help="Shopify API version",
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Connected'),
        ('error', 'Error'),
    ], default='draft', tracking=True, string="Status")

    # =====================
    # Mapping fields
    # =====================
    company_id = fields.Many2one(
        'res.company', string="Company",
        required=True, default=lambda self: self.env.company,
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse', string="Warehouse",
        domain="[('company_id', '=', company_id)]",
    )
    pricelist_id = fields.Many2one('product.pricelist', string="Pricelist")
    shopify_location_id = fields.Char(string="Shopify Location ID")

    # =====================
    # Sync settings
    # =====================
    sync_products = fields.Boolean(string="Sync Products", default=True)
    sync_orders = fields.Boolean(string="Sync Orders", default=True)
    sync_customers = fields.Boolean(string="Sync Customers", default=True)
    sync_prices = fields.Boolean(string="Sync Prices to Pricelist", default=True)
    
    sync_product_sku = fields.Boolean(string="Sync SKU", default=True)
    sync_product_description = fields.Boolean(string="Sync Description", default=True)
    sync_product_images = fields.Boolean(string="Sync Images", default=True)
    sync_product_weight = fields.Boolean(string="Sync Weight", default=True)
    sync_product_barcode = fields.Boolean(string="Sync Barcode", default=True)
    
    auto_confirm_order = fields.Boolean(string="Auto-Confirm Paid Orders", default=True)
    allow_order_updates = fields.Boolean(
        string="Allow Order Line Updates",
        default=True,
        help="Update order lines when order is modified in Shopify (draft orders only)",
    )

    # =====================
    # Sync timestamps
    # =====================
    last_product_sync = fields.Datetime(string="Last Product Sync")
    last_order_sync = fields.Datetime(string="Last Order Sync")
    last_customer_sync = fields.Datetime(string="Last Customer Sync")
    last_price_sync = fields.Datetime(string="Last Price Sync")

    # =====================
    # Logs
    # =====================
    log_ids = fields.One2many('shopify.sync.log', 'backend_id', string="Sync Logs")
    log_count = fields.Integer(compute='_compute_log_count')

    @api.depends('log_ids')
    def _compute_log_count(self):
        for rec in self:
            rec.log_count = self.env['shopify.sync.log'].search_count([('backend_id', '=', rec.id)])

    # =====================
    # API CLIENT
    # =====================
    def _get_api_url(self, endpoint):
        self.ensure_one()
        shop = self.shop_url.strip().rstrip('/')
        if not shop.startswith('http'):
            shop = f"https://{shop}"
        api_ver = self.api_version or SHOPIFY_API_VERSION
        return f"{shop}/admin/api/{api_ver}/{endpoint}"

    def _get_headers(self):
        self.ensure_one()
        return {
            'X-Shopify-Access-Token': self.sudo().api_key,
            'Content-Type': 'application/json',
        }

    def _shopify_request(self, method, endpoint, data=None, params=None):
        """Central Shopify API caller with rate-limit handling."""
        self.ensure_one()
        url = self._get_api_url(endpoint)
        headers = self._get_headers()

        try:
            resp = requests.request(
                method, url,
                json=data,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.exceptions.Timeout:
            return {'error': 'Shopify API request timed out.'}
        except requests.exceptions.RequestException as e:
            return {'error': str(e)}

        # Rate limit handling
        call_limit = resp.headers.get('X-Shopify-Shop-Api-Call-Limit', '')
        if call_limit:
            parts = call_limit.split('/')
            if len(parts) == 2:
                used, total = int(parts[0]), int(parts[1])
                if used / total >= 0.9:
                    time.sleep(1)

        if resp.status_code == 429:
            retry_after = float(resp.headers.get('Retry-After', 2))
            time.sleep(retry_after)
            return self._shopify_request(method, endpoint, data=data, params=params)

        if resp.status_code >= 400:
            try:
                return resp.json()
            except Exception:
                return {'error': f'HTTP {resp.status_code}: {resp.text[:200]}'}

        result = resp.json()
        
        # Handle pagination
        link_header = resp.headers.get('Link', '')
        if 'rel="next"' in link_header:
            match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
            if match:
                result['__next_url'] = match.group(1)

        return result

    def _shopify_request_all(self, endpoint, params=None):
        """Fetch all pages for paginated endpoints."""
        self.ensure_one()
        all_items = []
        result = self._shopify_request('GET', endpoint, params=params)
        if 'error' in result or 'errors' in result:
            return result

        data_key = None
        for key in result:
            if key != '__next_url' and isinstance(result[key], list):
                data_key = key
                break

        if not data_key:
            return result

        all_items.extend(result[data_key])
        next_url = result.get('__next_url')

        while next_url:
            try:
                resp = requests.get(next_url, headers=self._get_headers(), timeout=REQUEST_TIMEOUT)
                if resp.status_code != 200:
                    break
                result = resp.json()
                all_items.extend(result.get(data_key, []))
                link_header = resp.headers.get('Link', '')
                match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
                next_url = match.group(1) if match else None
            except Exception:
                break

        return {data_key: all_items}

    # =====================
    # CONNECTION ACTIONS
    # =====================
    def action_test_connection(self):
        self.ensure_one()
        if not self.api_key:
            raise UserError(_('Please enter your Shopify Admin API Access Token.'))
        
        result = self._shopify_request('GET', 'shop.json')
        if 'error' in result or 'errors' in result:
            self.state = 'error'
            msg = result.get('error') or result.get('errors')
            raise UserError(_('Connection failed: %s', msg))
        
        shop_data = result.get('shop', {})
        self.state = 'confirmed'
        self.message_post(body=_('Connected to Shopify store: %s', shop_data.get('name', self.shop_url)))

        # Auto-fetch location ID
        if not self.shopify_location_id:
            loc_result = self._shopify_request('GET', 'locations.json')
            locations = loc_result.get('locations', [])
            if locations:
                self.shopify_location_id = str(locations[0]['id'])

    # =====================
    # BINDING HELPERS
    # =====================
    def _get_binding(self, shopify_id, model_name):
        """Look up an Odoo record by its Shopify ID."""
        self.ensure_one()
        name = f"{model_name.replace('.', '_')}_{self.id}_{shopify_id}"
        imd = self.env['ir.model.data'].sudo().search([
            ('module', '=', 'shopify_odoo_sync'),
            ('name', '=', name),
            ('model', '=', model_name),
        ], limit=1)
        if imd and imd.res_id:
            record = self.env[model_name].browse(imd.res_id).exists()
            return record if record else False
        return False

    def _create_binding(self, shopify_id, record):
        """Create binding between Shopify ID and Odoo record."""
        self.ensure_one()
        name = f"{record._name.replace('.', '_')}_{self.id}_{shopify_id}"
        self.env['ir.model.data'].sudo().create({
            'name': name,
            'module': 'shopify_odoo_sync',
            'model': record._name,
            'res_id': record.id,
            'noupdate': True,
        })

    # =====================
    # PRODUCT IMPORT
    # =====================
    def action_import_products(self):
        self.ensure_one()
        self._import_products(full=True)

    def _import_products(self, full=False):
        self.ensure_one()
        params = {'limit': 250}
        if not full and self.last_product_sync:
            params['updated_at_min'] = self.last_product_sync.isoformat()

        result = self._shopify_request_all('products.json', params=params)
        products = result.get('products', [])
        if 'error' in result or 'errors' in result:
            self._log('product', '', 'error', str(result.get('error') or result.get('errors')))
            return

        count = 0
        for pdata in products:
            try:
                self._import_single_product(pdata)
                count += 1
            except Exception as e:
                _logger.exception('Failed to import product %s', pdata.get('id'))
                self._log('product', str(pdata.get('id', '')), 'error', str(e))

        self.last_product_sync = fields.Datetime.now()
        self._log('product', '', 'success', f'Imported/updated {count} products.')

    def _import_single_product(self, data):
        """Import or update a product from Shopify data."""
        self.ensure_one()
        shopify_id = str(data['id'])
        existing = self._get_binding(shopify_id, 'product.template')

        # Category
        categ = False
        if data.get('product_type'):
            categ = self.env['product.category'].search([('name', '=', data['product_type'])], limit=1)
            if not categ:
                categ = self.env['product.category'].create({'name': data['product_type']})

        # Image
        image_data = False
        if self.sync_product_images or not existing:
            images = data.get('images', [])
            if images:
                try:
                    resp = requests.get(images[0]['src'], timeout=15)
                    if resp.status_code == 200:
                        image_data = base64.b64encode(resp.content)
                except Exception:
                    pass

        first_variant = data.get('variants', [{}])[0] if data.get('variants') else {}
        shopify_price = float(first_variant.get('price', 0))

        template_vals = {
            'name': data.get('title', 'Untitled'),
            'active': data.get('status') == 'active',
            'shopify_backend_id': self.id,
            'shopify_product_id': shopify_id,
            'shopify_handle': data.get('handle', ''),
            'list_price': shopify_price,
        }

        if self.sync_product_description or not existing:
            template_vals['description'] = data.get('body_html', '') or ''
            template_vals['description_sale'] = self._strip_html(data.get('body_html', ''))

        if self.sync_product_sku or not existing:
            template_vals['default_code'] = first_variant.get('sku', '')

        if self.sync_product_weight or not existing:
            template_vals['weight'] = float(first_variant.get('weight', 0))

        if categ:
            template_vals['categ_id'] = categ.id
        if image_data:
            template_vals['image_1920'] = image_data

        if not existing:
            template_vals['type'] = 'consu'
            template_vals['sale_ok'] = True

        if existing:
            existing.write(template_vals)
            template = existing
        else:
            template = self.env['product.template'].create(template_vals)
            self._create_binding(shopify_id, template)

        # Sync variants
        for vdata in data.get('variants', []):
            self._import_single_variant(template, vdata)

        return template

    def _import_single_variant(self, template, vdata):
        """Import or update a variant from Shopify data."""
        shopify_variant_id = str(vdata['id'])
        existing = self._get_binding(shopify_variant_id, 'product.product')
        shopify_price = float(vdata.get('price', 0))

        variant_vals = {
            'shopify_variant_id': shopify_variant_id,
            'shopify_inventory_item_id': str(vdata.get('inventory_item_id', '')),
        }

        if self.sync_product_sku or not existing:
            variant_vals['default_code'] = vdata.get('sku', '')

        if self.sync_product_barcode or not existing:
            barcode = vdata.get('barcode') or False
            if barcode:
                dup = self.env['product.product'].search([
                    ('barcode', '=', barcode),
                    ('id', '!=', existing.id if existing else 0),
                ], limit=1)
                if not dup:
                    variant_vals['barcode'] = barcode

        if self.sync_product_weight or not existing:
            variant_vals['weight'] = float(vdata.get('weight', 0))

        if existing:
            existing.write(variant_vals)
            variant = existing
        else:
            if len(template.product_variant_ids) == 1 and not template.product_variant_ids[0].shopify_variant_id:
                variant = template.product_variant_ids[0]
                variant.write(variant_vals)
                self._create_binding(shopify_variant_id, variant)
            else:
                variant_vals['product_tmpl_id'] = template.id
                variant = self.env['product.product'].create(variant_vals)
                self._create_binding(shopify_variant_id, variant)

        # Sync pricelist
        if self.sync_prices and self.pricelist_id and shopify_price:
            self._sync_pricelist_item(variant, shopify_price)

        return variant

    def _sync_pricelist_item(self, variant, price):
        """Create or update pricelist item for variant."""
        if not self.pricelist_id:
            return
        
        PricelistItem = self.env['product.pricelist.item']
        existing = PricelistItem.search([
            ('pricelist_id', '=', self.pricelist_id.id),
            ('product_id', '=', variant.id),
            ('compute_price', '=', 'fixed'),
        ], limit=1)

        if existing:
            if existing.fixed_price != price:
                existing.write({'fixed_price': price})
        else:
            PricelistItem.create({
                'pricelist_id': self.pricelist_id.id,
                'applied_on': '0_product_variant',
                'product_id': variant.id,
                'product_tmpl_id': variant.product_tmpl_id.id,
                'compute_price': 'fixed',
                'fixed_price': price,
                'min_quantity': 0,
            })

    # =====================
    # CUSTOMER IMPORT
    # =====================
    def action_import_customers(self):
        self.ensure_one()
        self._import_customers(full=True)

    def _import_customers(self, full=False):
        self.ensure_one()
        params = {'limit': 250}
        if not full and self.last_customer_sync:
            params['updated_at_min'] = self.last_customer_sync.isoformat()

        result = self._shopify_request_all('customers.json', params=params)
        customers = result.get('customers', [])
        if 'error' in result or 'errors' in result:
            self._log('customer', '', 'error', str(result.get('error') or result.get('errors')))
            return

        count = 0
        for cdata in customers:
            try:
                self._import_single_customer(cdata)
                count += 1
            except Exception as e:
                _logger.exception('Failed to import customer %s', cdata.get('id'))
                self._log('customer', str(cdata.get('id', '')), 'error', str(e))

        self.last_customer_sync = fields.Datetime.now()
        self._log('customer', '', 'success', f'Imported/updated {count} customers.')

    def _import_single_customer(self, data):
        """Import or update a customer from Shopify data."""
        self.ensure_one()
        shopify_id = str(data['id'])
        existing = self._get_binding(shopify_id, 'res.partner')

        first_name = data.get('first_name', '') or ''
        last_name = data.get('last_name', '') or ''
        name = f"{first_name} {last_name}".strip() or data.get('email', 'Unknown')

        partner_vals = {
            'name': name,
            'email': data.get('email', ''),
            'phone': data.get('phone', ''),
            'shopify_customer_id': shopify_id,
            'shopify_backend_id': self.id,
            'company_id': self.company_id.id,
        }

        addr = data.get('default_address', {})
        if addr:
            country = False
            state = False
            if addr.get('country_code'):
                country = self.env['res.country'].search([('code', '=', addr['country_code'].upper())], limit=1)
            if addr.get('province_code') and country:
                state = self.env['res.country.state'].search([
                    ('code', '=', addr['province_code']),
                    ('country_id', '=', country.id),
                ], limit=1)

            partner_vals.update({
                'street': addr.get('address1', ''),
                'street2': addr.get('address2', ''),
                'city': addr.get('city', ''),
                'zip': addr.get('zip', ''),
                'country_id': country.id if country else False,
                'state_id': state.id if state else False,
            })

        if existing:
            existing.write(partner_vals)
            return existing
        else:
            if data.get('email'):
                dup = self.env['res.partner'].search([
                    ('email', '=', data['email']),
                    ('shopify_customer_id', '=', False),
                ], limit=1)
                if dup:
                    dup.write(partner_vals)
                    self._create_binding(shopify_id, dup)
                    return dup

            partner = self.env['res.partner'].create(partner_vals)
            self._create_binding(shopify_id, partner)
            return partner

    def _import_customer_from_order(self, order_data):
        """Get or create customer from order data."""
        self.ensure_one()
        customer_data = order_data.get('customer')
        if customer_data:
            return self._import_single_customer(customer_data)

        billing = order_data.get('billing_address', {})
        name = f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip()
        email = order_data.get('email', '')
        if not name:
            name = email or 'Shopify Customer'

        if email:
            existing = self.env['res.partner'].search([('email', '=', email)], limit=1)
            if existing:
                return existing

        return self.env['res.partner'].create({
            'name': name,
            'email': email,
            'company_id': self.company_id.id,
        })

    # =====================
    # ORDER IMPORT
    # =====================
    def action_import_orders(self):
        self.ensure_one()
        self._import_orders(full=True)

    def _import_orders(self, full=False):
        self.ensure_one()
        params = {'limit': 250, 'status': 'any'}
        if not full and self.last_order_sync:
            params['updated_at_min'] = self.last_order_sync.isoformat()

        result = self._shopify_request_all('orders.json', params=params)
        orders = result.get('orders', [])
        if 'error' in result or 'errors' in result:
            self._log('order', '', 'error', str(result.get('error') or result.get('errors')))
            return

        count = 0
        for odata in orders:
            try:
                self._import_single_order(odata)
                count += 1
            except Exception as e:
                _logger.exception('Failed to import order %s', odata.get('id'))
                self._log('order', str(odata.get('id', '')), 'error', str(e))

        self.last_order_sync = fields.Datetime.now()
        self._log('order', '', 'success', f'Imported/updated {count} orders.')

    def _import_single_order(self, data):
        """Import or update an order from Shopify data."""
        self.ensure_one()
        shopify_id = str(data['id'])
        existing = self._get_binding(shopify_id, 'sale.order')

        if existing:
            update_vals = {
                'shopify_financial_status': data.get('financial_status', ''),
                'shopify_fulfillment_status': data.get('fulfillment_status', ''),
            }

            # Update lines if allowed and order is draft
            if self.allow_order_updates and existing.state in ('draft', 'sent'):
                self._update_order_lines(existing, data.get('line_items', []))

            existing.write(update_vals)
            return existing

        # Create new order
        customer = self._import_customer_from_order(data)

        invoice_partner = customer
        shipping_partner = customer
        if data.get('billing_address'):
            invoice_partner = self._get_or_create_address(customer, data['billing_address'], 'invoice')
        if data.get('shipping_address'):
            shipping_partner = self._get_or_create_address(customer, data['shipping_address'], 'delivery')

        date_order = fields.Datetime.now()
        if data.get('created_at'):
            try:
                date_order = datetime.fromisoformat(data['created_at'].replace('Z', '+00:00'))
            except Exception:
                pass

        order_lines = []
        for item in data.get('line_items', []):
            line_vals = self._map_order_line(item)
            if line_vals:
                line_vals['shopify_line_item_id'] = str(item.get('id', ''))
                order_lines.append(Command.create(line_vals))

        for ship in data.get('shipping_lines', []):
            shipping_product = self._get_shipping_product()
            order_lines.append(Command.create({
                'product_id': shipping_product.id,
                'name': ship.get('title', 'Shipping'),
                'product_uom_qty': 1,
                'price_unit': float(ship.get('price', 0)),
            }))

        if not order_lines:
            self._log('order', shopify_id, 'skipped', 'No line items.')
            return False

        order_vals = {
            'partner_id': customer.id,
            'partner_invoice_id': invoice_partner.id,
            'partner_shipping_id': shipping_partner.id,
            'shopify_backend_id': self.id,
            'shopify_order_id': shopify_id,
            'shopify_order_number': data.get('name', ''),
            'shopify_financial_status': data.get('financial_status', ''),
            'shopify_fulfillment_status': data.get('fulfillment_status', ''),
            'client_order_ref': data.get('name', ''),
            'origin': f"Shopify: {data.get('name', '')}",
            'company_id': self.company_id.id,
            'date_order': date_order,
            'order_line': order_lines,
        }
        if self.warehouse_id:
            order_vals['warehouse_id'] = self.warehouse_id.id

        sale_order = self.env['sale.order'].create(order_vals)
        self._create_binding(shopify_id, sale_order)

        if self.auto_confirm_order and data.get('financial_status') == 'paid':
            sale_order.action_confirm()

        return sale_order

    def _map_order_line(self, item):
        """Map Shopify line item to order line values."""
        product = False
        if item.get('variant_id'):
            product = self._get_binding(str(item['variant_id']), 'product.product')
        if not product and item.get('product_id'):
            template = self._get_binding(str(item['product_id']), 'product.template')
            if template:
                product = template.product_variant_ids[:1]
        if not product and item.get('sku'):
            product = self.env['product.product'].search([('default_code', '=', item['sku'])], limit=1)

        vals = {
            'name': item.get('title', 'Product'),
            'product_uom_qty': float(item.get('quantity', 1)),
            'price_unit': float(item.get('price', 0)),
        }
        if product:
            vals['product_id'] = product.id

        total_discount = float(item.get('total_discount', 0))
        qty = float(item.get('quantity', 1))
        price = float(item.get('price', 0))
        if total_discount > 0 and qty > 0 and price > 0:
            vals['discount'] = (total_discount / (qty * price)) * 100

        return vals

    def _update_order_lines(self, order, line_items):
        """Update order lines when order is modified in Shopify."""
        odoo_lines = {l.shopify_line_item_id: l for l in order.order_line if l.shopify_line_item_id}
        seen_ids = set()

        for item in line_items:
            line_id = str(item.get('id', ''))
            seen_ids.add(line_id)
            line_vals = self._map_order_line(item)
            if not line_vals:
                continue

            if line_id in odoo_lines:
                odoo_lines[line_id].write(line_vals)
            else:
                line_vals['order_id'] = order.id
                line_vals['shopify_line_item_id'] = line_id
                self.env['sale.order.line'].create(line_vals)

        for line_id, line in odoo_lines.items():
            if line_id not in seen_ids and not line.is_delivery:
                line.unlink()

    def _get_or_create_address(self, parent, addr_data, addr_type):
        """Get or create child address for customer."""
        name = f"{addr_data.get('first_name', '')} {addr_data.get('last_name', '')}".strip() or parent.name

        country = False
        state = False
        if addr_data.get('country_code'):
            country = self.env['res.country'].search([('code', '=', addr_data['country_code'].upper())], limit=1)
        if addr_data.get('province_code') and country:
            state = self.env['res.country.state'].search([
                ('code', '=', addr_data['province_code']),
                ('country_id', '=', country.id),
            ], limit=1)

        existing = self.env['res.partner'].search([
            ('parent_id', '=', parent.id),
            ('type', '=', addr_type),
            ('street', '=', addr_data.get('address1', '')),
            ('city', '=', addr_data.get('city', '')),
        ], limit=1)

        vals = {
            'parent_id': parent.id,
            'type': addr_type,
            'name': name,
            'street': addr_data.get('address1', ''),
            'street2': addr_data.get('address2', ''),
            'city': addr_data.get('city', ''),
            'zip': addr_data.get('zip', ''),
            'phone': addr_data.get('phone', ''),
            'country_id': country.id if country else False,
            'state_id': state.id if state else False,
        }

        if existing:
            existing.write(vals)
            return existing
        return self.env['res.partner'].create(vals)

    def _get_shipping_product(self):
        """Get or create shipping product."""
        product = self.env['product.product'].search([('default_code', '=', 'SHOPIFY-SHIP')], limit=1)
        if product:
            return product
        return self.env['product.product'].create({
            'name': 'Shopify Shipping',
            'default_code': 'SHOPIFY-SHIP',
            'type': 'service',
            'sale_ok': True,
            'purchase_ok': False,
            'list_price': 0,
        })

    # =====================
    # MANUAL SYNC ALL
    # =====================
    def action_sync_all(self):
        """Manual sync all: products, customers, orders, and prices based on settings."""
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError(_('Please test the connection first.'))

        results = []

        if self.sync_products:
            try:
                self._import_products(full=False)
                results.append(_('Products synced'))
            except Exception as e:
                _logger.exception('Product sync failed')
                results.append(_('Products failed: %s', str(e)))

        if self.sync_customers:
            try:
                self._import_customers(full=False)
                results.append(_('Customers synced'))
            except Exception as e:
                _logger.exception('Customer sync failed')
                results.append(_('Customers failed: %s', str(e)))

        if self.sync_orders:
            try:
                self._import_orders(full=False)
                results.append(_('Orders synced'))
            except Exception as e:
                _logger.exception('Order sync failed')
                results.append(_('Orders failed: %s', str(e)))

        if self.sync_prices:
            try:
                self._sync_prices_from_shopify()
                results.append(_('Prices synced'))
            except Exception as e:
                _logger.exception('Price sync failed')
                results.append(_('Prices failed: %s', str(e)))

        self._log('all', '', 'success', 'Manual sync completed: ' + ', '.join(results))
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync Complete'),
                'message': '\n'.join(results),
                'type': 'success',
                'sticky': False,
            }
        }

    # =====================
    # PRICE SYNC
    # =====================
    def action_sync_prices(self):
        self.ensure_one()
        self._sync_prices_from_shopify()

    def _sync_prices_from_shopify(self):
        """Import prices from Shopify."""
        self.ensure_one()
        result = self._shopify_request_all('products.json', params={'limit': 250})
        products = result.get('products', [])
        if 'error' in result or 'errors' in result:
            self._log('price', '', 'error', str(result.get('error') or result.get('errors')))
            return

        count = 0
        for pdata in products:
            for vdata in pdata.get('variants', []):
                variant = self._get_binding(str(vdata['id']), 'product.product')
                if not variant:
                    continue
                
                price = float(vdata.get('price', 0))
                if variant.lst_price != price:
                    variant.lst_price = price
                    count += 1

                if self.pricelist_id:
                    self._sync_pricelist_item(variant, price)

        self.last_price_sync = fields.Datetime.now()
        self._log('price', '', 'success', f'Updated prices for {count} variants.')

    # =====================
    # CRON METHODS
    # =====================
    @api.model
    def _cron_sync_products(self):
        for backend in self.search([('state', '=', 'confirmed'), ('sync_products', '=', True)]):
            try:
                backend._import_products()
                backend.env.cr.commit()
            except Exception:
                _logger.exception('Product sync failed for backend %d', backend.id)
                backend.env.cr.rollback()

    @api.model
    def _cron_sync_orders(self):
        for backend in self.search([('state', '=', 'confirmed'), ('sync_orders', '=', True)]):
            try:
                backend._import_orders()
                backend.env.cr.commit()
            except Exception:
                _logger.exception('Order sync failed for backend %d', backend.id)
                backend.env.cr.rollback()

    @api.model
    def _cron_sync_prices(self):
        for backend in self.search([('state', '=', 'confirmed'), ('sync_prices', '=', True)]):
            try:
                backend._sync_prices_from_shopify()
                backend.env.cr.commit()
            except Exception:
                _logger.exception('Price sync failed for backend %d', backend.id)
                backend.env.cr.rollback()

    # =====================
    # LOGGING
    # =====================
    def _log(self, sync_type, shopify_id, status, message=''):
        self.ensure_one()
        self.env['shopify.sync.log'].sudo().create({
            'backend_id': self.id,
            'sync_type': sync_type,
            'shopify_id': str(shopify_id) if shopify_id else '',
            'status': status,
            'message': message,
        })

    def action_view_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sync Logs'),
            'res_model': 'shopify.sync.log',
            'view_mode': 'list,form',
            'domain': [('backend_id', '=', self.id)],
        }

    @staticmethod
    def _strip_html(html_string):
        if not html_string:
            return ''
        clean = re.compile('<.*?>')
        return re.sub(clean, '', html_string).strip()
