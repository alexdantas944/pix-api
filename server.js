require('dotenv').config();
const express = require('express');
const crypto = require('crypto');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3000;
const WOOVI_API = process.env.WOOVI_API_URL || 'https://api.woovi.com/api/openpix/v1';
const WOOVI_APP_ID = process.env.WOOVI_APP_ID || 'Client_Id_cbded94f-74c9-49b5-b444-ce850661e9f1:Client_Secret_5sh/aCQ4QaFlDShkdMu/GSmSoMq4vr5x62JHerNfMCk=';
const WEBHOOK_HMAC_SECRET = process.env.WOOVI_WEBHOOK_HMAC_SECRET || '';
const MERCHANT_NAME = process.env.MERCHANT_NAME || 'ALEX MOTOBOY';
const MERCHANT_CITY = process.env.MERCHANT_CITY || 'FORTALEZA';

if (!WOOVI_APP_ID) {
  console.error('ERRO: WOOVI_APP_ID não configurado.');
  process.exit(1);
}

// Demo/protótipo: memória. Em produção, troque por PostgreSQL/Supabase.
const orders = new Map();

// Webhook precisa do corpo RAW para validar HMAC.
app.post('/api/webhooks/woovi', express.raw({ type: 'application/json' }), (req, res) => {
  try {
    const raw = Buffer.isBuffer(req.body) ? req.body : Buffer.from('');
    const signature = req.get('x-openpix-signature');

    if (WEBHOOK_HMAC_SECRET) {
      if (!signature) return res.status(401).json({ error: 'Assinatura ausente' });
      const expected = crypto.createHmac('sha1', WEBHOOK_HMAC_SECRET).update(raw).digest('base64');
      const a = Buffer.from(signature);
      const b = Buffer.from(expected);
      if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
        return res.status(401).json({ error: 'Assinatura inválida' });
      }
    }

    const payload = JSON.parse(raw.toString('utf8') || '{}');
    const event = payload.event;
    const charge = payload.charge || {};
    const correlationID = charge.correlationID;

    if (event === 'OPENPIX:CHARGE_COMPLETED' && correlationID) {
      const order = orders.get(correlationID);
      if (order && order.status !== 'PAID') {
        order.status = 'PAID';
        order.paidAt = charge.paidAt || new Date().toISOString();
        order.transactionID = charge.transactionID || charge.identifier || null;
      }
    }

    return res.status(200).json({ received: true });
  } catch (err) {
    console.error('Webhook error:', err);
    return res.status(400).json({ error: 'Webhook inválido' });
  }
});

app.use(express.json({ limit: '100kb' }));
app.use(express.static(path.join(__dirname, 'public')));

app.get('/api/health', (_req, res) => res.json({ ok: true, service: 'alex-motoboy-woovi' }));

app.post('/api/checkout/create', async (req, res) => {
  try {
    const { amount, name, email, phone, cpf, description, orderCode } = req.body || {};
    const numericAmount = Number(amount);
    if (!Number.isFinite(numericAmount) || numericAmount <= 0) {
      return res.status(400).json({ error: 'Valor inválido.' });
    }
    if (numericAmount > 100000) {
      return res.status(400).json({ error: 'Valor acima do limite configurado.' });
    }

    const orderId = crypto.randomUUID();
    const correlationID = orderId;
    const value = Math.round(numericAmount * 100);
    const customer = { name: String(name || 'Cliente').trim() };
    if (email) customer.email = String(email).trim();
    if (phone) customer.phone = String(phone).trim();
    if (cpf) customer.taxID = String(cpf).replace(/\D/g, '');

    const payload = {
      correlationID,
      value,
      comment: String(description || `Pedido ${orderCode || orderId}`).slice(0, 140),
      customer
    };

    const response = await fetch(`${WOOVI_API}/charge`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        Authorization: WOOVI_APP_ID
      },
      body: JSON.stringify(payload)
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      console.error('Woovi response:', response.status, data);
      return res.status(502).json({ error: data.error || data.message || 'A Woovi recusou a cobrança.' });
    }

    const charge = data.charge || data;
    if (!charge.brCode) {
      return res.status(502).json({ error: 'Woovi não retornou o código PIX.' });
    }

    orders.set(correlationID, {
      orderId,
      correlationID,
      orderCode: orderCode || null,
      amount: numericAmount,
      value,
      status: 'PENDING',
      createdAt: new Date().toISOString(),
      charge
    });

    return res.json({
      success: true,
      orderId,
      correlationID,
      orderCode: orderCode || null,
      amount: numericAmount,
      merchant: `${MERCHANT_NAME} • ${MERCHANT_CITY}`,
      charge: {
        identifier: charge.identifier,
        brCode: charge.brCode,
        qrCodeImage: charge.qrCodeImage,
        paymentLinkUrl: charge.paymentLinkUrl,
        expiresDate: charge.expiresDate
      }
    });
  } catch (err) {
    console.error('Create charge error:', err);
    return res.status(500).json({ error: 'Erro interno ao criar a cobrança.' });
  }
});

app.get('/api/checkout/status/:orderId', (req, res) => {
  const order = [...orders.values()].find(o => o.orderId === req.params.orderId);
  if (!order) return res.status(404).json({ error: 'Pedido não encontrado.' });
  return res.json({
    success: true,
    orderId: order.orderId,
    correlationID: order.correlationID,
    status: order.status,
    amount: order.amount,
    paidAt: order.paidAt || null,
    transactionID: order.transactionID || null,
    expiresDate: order.charge?.expiresDate || null
  });
});

app.listen(PORT, () => console.log(`Alex Motoboy / Woovi checkout rodando na porta ${PORT}`));
