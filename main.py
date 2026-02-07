from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client
import segno
import base64
import uuid
import os
from unidecode import unidecode
from io import BytesIO
from typing import Optional

# --- INICIALIZAÇÃO ---
app = FastAPI(title="API Pix Pixels - Supabase Edition")

# --- CONFIGURAÇÃO DE CORS ---
# Permite que seu site (localhost ou outro) acesse a API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONEXÃO SUPABASE ---
# As variáveis abaixo devem ser configuradas no Painel do Render (Environment)
URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")

if not URL or not KEY:
    # Aviso no log do Render caso as chaves não tenham sido preenchidas
    print("ERRO CRÍTICO: Variáveis SUPABASE_URL ou SUPABASE_KEY não configuradas!")
    supabase = None
else:
    supabase: Client = create_client(URL, KEY)

# --- MODELOS DE DADOS ---
class PixRequest(BaseModel):
    chave: str
    nome: str
    cidade: str
    valor: float
    txid: Optional[str] = "WEBPIX"

# --- LÓGICA PIX ---
class PixService:
    @staticmethod
    def _crc16(payload: str) -> str:
        crc = 0xFFFF
        for byte in payload.encode('utf-8'):
            crc ^= (byte << 8)
            for _ in range(8):
                crc = (crc << 1) ^ 0x1021 if (crc & 0x8000) else crc << 1
        return hex(crc & 0xFFFF)[2:].upper().zfill(4)

    @classmethod
    def gerar(cls, d: PixRequest):
        def f(id, v): return f"{id}{len(v):02}{v}"
        
        campos = [
            f("00", "01"),
            f("26", f("00", "br.gov.bcb.pix") + f("01", d.chave)),
            f("52", "0000"),
            f("53", "986"),
            f("54", f"{d.valor:.2f}"),
            f("58", "BR"),
            f("59", unidecode(d.nome).upper()[:25]),
            f("60", unidecode(d.cidade).upper()[:15]),
            f("62", f("05", d.txid[:25])),
            "6304"
        ]
        
        pre_payload = "".join(campos)
        return pre_payload + cls._crc16(pre_payload)

# --- ENDPOINTS ---

@app.get("/")
def health_check():
    status = "conectado" if supabase else "sem_banco_de_dados"
    return {"status": "online", "supabase": status}

@app.post("/api/v1/pix")
async def criar_pix(request: PixRequest):
    if not supabase:
        raise HTTPException(status_code=500, detail="Banco de dados não configurado no Render.")

    id_venda = str(uuid.uuid4())[:8]
    payload_pix = PixService.gerar(request)
    
    # 1. Salva a transação no Supabase
    try:
        data = {
            "id": id_venda,
            "valor": request.valor,
            "txid": request.txid,
            "status": "PENDENTE"
        }
        supabase.table("transacoes").insert(data).execute()
    except Exception as e:
        print(f"Erro Supabase: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar no banco.")

    # 2. Gera o QR Code
    qr = segno.make(payload_pix, error='M')
    buffer = BytesIO()
    qr.save(buffer, kind='png', scale=10)
    qr_base64 = f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"
    
    return {
        "id_transacao": id_venda,
        "payload": payload_pix,
        "qrcode_base64": qr_base64
    }

@app.get("/api/v1/status/{id_transacao}")
async def checar_status(id_transacao: str):
    response = supabase.table("transacoes").select("status").eq("id", id_transacao).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Transação não encontrada")
    return {"status": response.data[0]["status"]}

# --- ENDPOINTS EXCLUSIVOS DO ADMIN ---

@app.get("/api/v1/admin/todas")
async def listar_todas():
    # Retorna as últimas 20 transações para o Painel Admin
    response = supabase.table("transacoes").select("*").order("created_at", desc=True).limit(20).execute()
    return response.data

@app.get("/api/v1/admin/confirmar/{id_transacao}")
async def confirmar_pagamento(id_transacao: str):
    # Atualiza o status para PAGO
    supabase.table("transacoes").update({"status": "PAGO"}).eq("id", id_transacao).execute()
    return {"message": "Pagamento confirmado com sucesso!"}
