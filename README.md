# Checkout Alex Motoboy + Woovi/OpenPix v4

## Fluxo
1. `public/index.html` envia a venda para `/api/checkout/create`.
2. `server.js` cria a cobrança Pix na Woovi usando `WOOVI_APP_ID`.
3. O HTML exibe QR Code e PIX Copia e Cola.
4. O frontend consulta `/api/checkout/status/:orderId` a cada 3 segundos.
5. Woovi envia `OPENPIX:CHARGE_COMPLETED` para `/api/webhooks/woovi`.
6. O backend marca a cobrança como `PAID` e o checkout mostra "Pagamento confirmado".

## Configuração
1. Copie `.env.example` para `.env`.
2. Coloque um AppID novo da Woovi em `WOOVI_APP_ID`.
3. Configure um webhook da Woovi para:
   `https://SEU-DOMINIO/api/webhooks/woovi`
4. Se usar HMAC, coloque a secret em `WOOVI_WEBHOOK_HMAC_SECRET`.
5. Rode `npm install` e `npm start`.

## Importante
O HTML não contém AppID nem secret. Nunca coloque essas credenciais em HTML/JavaScript do navegador.

Para produção, substitua o Map em memória por PostgreSQL/Supabase para persistência e idempotência durável.


TESTE LOCAL
Esta versão contém a credencial fornecida na conversa apenas para teste. Não publique esta versão. Rotacione a credencial antes de produção.
